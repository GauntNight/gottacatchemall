"""Tier 2 / Phase 3 — Target via the unofficial RedSky API.

RedSky is undocumented and drifts without notice, so this fetcher is
best-effort: anything unexpected -> UNKNOWN, never an exception.

Discovered live (2026-06-12) for the Pitch Black ETB (TCIN 1011483406):

* The ``key`` is a *static, public* web key baked into target.com's
  frontend — the same for every shopper. We ship a known-good default
  so the watcher works out of the box; override via ``options.key``.
* Availability is NOT in ``pdp_client_v1`` (its ``fulfillment`` is null)
  and the old ``pdp_fulfillment_v1`` endpoint is now ``410 Gone``. Stock
  lives in ``product_fulfillment_v1`` under
  ``fulfillment.shipping_options.availability_status`` (national, so the
  exact lat/long barely matters). Title/price come from ``pdp_client_v1``.

**Akamai + the browser fallback.** RedSky is Akamai-protected. Plain HTTP
works from a clean IP but gets a sticky 403 once the IP/fingerprint is
flagged (datacenter IPs, or after a burst). So on a 403 we transparently
retry the *same* JSON calls from inside a warmed target.com page via the
shared stealth browser — the request then carries Akamai's validated
``_abck`` cookie and the right Origin, exactly like the live site. No
config needed; set ``options.browser: true`` to skip straight to the
browser on an IP you know is blocked.

    options:
      tcin: "1011483406"   # required (the A-<tcin> in the product URL)
      key:  "<web_key>"     # optional; defaults to the shipped public key
      store_id / zip / state / latitude / longitude   # optional location
      browser: false        # force the browser path (skip the httpx attempt)
      headless: false        # browser-path: headless is challenged; keep headed
      settle_ms: 6000
"""

from __future__ import annotations

import html
import json
import logging
from urllib.parse import urlencode

import httpx

from ..browser import launch_stealth_persistent_context
from ..config import Target
from ..http import BROWSER_USER_AGENT
from ..models import Observation, Status
from .base import register

log = logging.getLogger("tcgmon.redsky")

PROFILE_DIR = ".target_profile"
_WARM_URL = "https://www.target.com/"
_BASE = "https://redsky.target.com/redsky_aggregations/v1/web"
_FULFILLMENT = f"{_BASE}/product_fulfillment_v1"
_PDP = f"{_BASE}/pdp_client_v1"

# Long-standing public web key baked into target.com's frontend. Public by
# design (it ships in the page JS); override via options.key if it rotates.
_DEFAULT_KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"

_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": "application/json",
    "Origin": "https://www.target.com",
    "Referer": "https://www.target.com/",
}

# shipping_options.availability_status string -> our three-valued Status.
_IN = {"IN_STOCK", "AVAILABLE", "PRE_ORDER_SELLABLE", "PRE_ORDER", "LIMITED_STOCK"}
_OUT = {"OUT_OF_STOCK", "UNAVAILABLE", "NOT_AVAILABLE"}


def parse_fulfillment(data: object) -> Status:
    """``product_fulfillment_v1`` JSON -> Status. Unknown shapes -> UNKNOWN."""
    try:
        fulfillment = (data["data"]["product"] or {}).get("fulfillment") or {}
        ship = fulfillment.get("shipping_options") or {}
        status_str = (ship.get("availability_status") or "").upper()
        qty = ship.get("available_to_promise_quantity")
    except (KeyError, TypeError):
        return Status.UNKNOWN
    if status_str in _IN:
        return Status.IN_STOCK
    if status_str in _OUT:
        return Status.OUT_OF_STOCK
    # Recognised-shape fallback: a real numeric ATP quantity is trustworthy
    # even if the status string drifts.
    if isinstance(qty, (int, float)):
        return Status.IN_STOCK if qty > 0 else Status.OUT_OF_STOCK
    return Status.UNKNOWN


def parse_pdp(data: object) -> tuple[str | None, str | None]:
    """``pdp_client_v1`` JSON -> (title, formatted price). Missing -> Nones."""
    try:
        product = data["data"]["product"]
        item = product.get("item", {})
        raw_title = (item.get("product_description") or {}).get("title")
        title = html.unescape(raw_title) if raw_title else None
        price = (product.get("price") or {}).get("formatted_current_price")
        return title, price
    except (KeyError, TypeError):
        return None, None


async def _browser_fetch_json(urls: list[str], *, headless: bool,
                              settle_ms: int) -> list[object | None]:
    """Fetch each JSON URL from inside a warmed target.com page, so the request
    carries Akamai's validated cookie + the target.com Origin."""
    from playwright.async_api import async_playwright

    results: list[object | None] = [None] * len(urls)
    async with async_playwright() as p:
        ctx = await launch_stealth_persistent_context(
            p, user_data_dir=PROFILE_DIR, user_agent=BROWSER_USER_AGENT,
            headless=headless,
        )
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(_WARM_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(settle_ms)
            for i, u in enumerate(urls):
                try:
                    txt = await page.evaluate(
                        "async (u) => { const r = await fetch(u, {headers:"
                        "{'accept':'application/json'}, credentials:'include'});"
                        " return r.ok ? await r.text() : null; }", u,
                    )
                    if txt:
                        results[i] = json.loads(txt)
                except Exception:  # noqa: BLE001 — one call failing is fine
                    pass
        finally:
            await ctx.close()
    return results


@register("redsky")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    tcin = target.options.get("tcin")
    key = target.options.get("key") or _DEFAULT_KEY
    obs_key = f"target:{tcin or target.name}"
    unknown = [Observation(key=obs_key, status=Status.UNKNOWN,
                           title=target.name, url=target.url)]
    if not tcin:
        log.warning("[%s] redsky needs options.tcin (the A-<tcin> in the URL)", target.name)
        return unknown

    store_id = target.options.get("store_id", "1234")
    f_params = {
        "key": key, "tcin": tcin, "store_id": store_id,
        "zip": target.options.get("zip", "10001"),
        "state": target.options.get("state", "NY"),
        "latitude": target.options.get("latitude", "40.71"),
        "longitude": target.options.get("longitude", "-74.00"),
        "required_store_id": store_id, "has_required_store_id": "true",
    }
    p_params = {"key": key, "tcin": tcin, "pricing_store_id": store_id}

    force_browser = bool(target.options.get("browser", False))
    data_f: object | None = None
    data_p: object | None = None
    blocked = force_browser

    # --- primary: plain HTTP (works from a clean IP) ----------------------
    if not force_browser:
        try:
            resp = await client.get(_FULFILLMENT, params=f_params, headers=_HEADERS)
            if resp.status_code == 403:
                blocked = True
            else:
                resp.raise_for_status()
                data_f = resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 403:
                blocked = True
            else:
                log.warning("[%s] fulfillment fetch failed: %s", target.name, exc)
                return unknown
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("[%s] fulfillment fetch failed: %s", target.name, exc)
            return unknown
        if data_f is not None:
            try:  # best-effort title/price enrichment
                pdp = await client.get(_PDP, params=p_params, headers=_HEADERS)
                if pdp.status_code == 200:
                    data_p = pdp.json()
            except (httpx.HTTPError, ValueError):
                pass

    # --- fallback: fetch both from a warmed target.com browser context ----
    if blocked:
        try:
            from playwright.async_api import async_playwright  # noqa: F401
            results = await _browser_fetch_json(
                [f"{_FULFILLMENT}?{urlencode(f_params)}", f"{_PDP}?{urlencode(p_params)}"],
                headless=bool(target.options.get("headless", False)),
                settle_ms=int(target.options.get("settle_ms", 6000)),
            )
            data_f, data_p = results[0], results[1]
            if data_f is not None:
                log.info("[%s] redsky served via browser (httpx blocked)", target.name)
        except ImportError:
            log.warning("[%s] blocked and playwright missing — install \".[browser]\"",
                        target.name)
            return unknown
        except Exception as exc:  # noqa: BLE001 — fail soft on any browser error
            log.warning("[%s] browser redsky failed: %s", target.name, exc)
            return unknown

    if data_f is None:
        log.info("[%s] no fulfillment data (challenged) -> UNKNOWN", target.name)
        return unknown

    status = parse_fulfillment(data_f)
    title, price = target.name, None
    if data_p is not None:
        t, pr = parse_pdp(data_p)
        title, price = (t or target.name), pr
    return [Observation(key=obs_key, status=status, title=title,
                        url=target.url, price=price)]
