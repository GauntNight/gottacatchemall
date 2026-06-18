"""Tier 2 / Phase 3 — Target LOCAL pickup sweep across nearby stores.

Resolves the stores near a zip via redsky ``nearby_stores_v1``, then checks
in-store **Order Pickup** for the TCIN at each one
(``store_options[0].order_pickup``) — all in ONE stealth-browser session, so a
12-store sweep is one browser launch, not twelve. Emits one Observation per
store, keyed ``target:<tcin>:store:<id>``, so every store is an independent
edge / signal (you get a push naming the store that just opened pickup).

A ``states`` filter keeps the sweep to your side of a metro line — e.g. NJ-only
from Edgewater, skipping the NYC stores a 25-mile radius would otherwise pull
in across the Hudson.

    options:
      tcin: "1011483406"   # required
      zip: "07020"          # sweep center (redsky `place`)
      within: 25            # radius, miles
      limit: 12             # max stores after filtering (caps browser work)
      states: ["NJ"]        # optional allow-list (abbrev or full name)
      key / headless / settle_ms

Prereqs:  pip install -e ".[browser]"  &&  playwright install chromium
"""

from __future__ import annotations

import json
import logging
from urllib.parse import urlencode

import httpx

from ..browser import launch_stealth_persistent_context
from ..config import Target
from ..http import BROWSER_USER_AGENT
from ..models import Observation, Status
from .base import register
from .redsky import _DEFAULT_KEY, parse_fulfillment, parse_pdp

log = logging.getLogger("tcgmon.target_nearby")

# Reuse the online watcher's profile: it's warmed/validated against Akamai by
# repeated runs, where a fresh profile gets challenged. This fetcher emits the
# online (shipping) signal too, so it's the SINGLE Target browser job on this
# profile — no concurrent-context contention.
PROFILE_DIR = ".target_profile"
_WARM_URL = "https://www.target.com/"
_BASE = "https://redsky.target.com/redsky_aggregations/v1/web"
_NEARBY = f"{_BASE}/nearby_stores_v1"
_FULFILLMENT = f"{_BASE}/product_fulfillment_v1"
_PDP = f"{_BASE}/pdp_client_v1"

# Enough aliasing to match the API's full state names against short configs.
_STATE_ALIASES = {
    "nj": "new jersey", "ny": "new york", "pa": "pennsylvania",
    "ct": "connecticut", "de": "delaware", "ny.": "new york",
}


def _norm_state(s: str | None) -> str:
    s = (s or "").strip().lower()
    return _STATE_ALIASES.get(s, s)


# Reverse map: full state name -> USPS abbrev. redsky's fulfillment endpoint
# 400s on a full state name ("New Jersey"); it wants "NJ".
_ABBREV = {full: ab.upper() for ab, full in _STATE_ALIASES.items() if len(ab) == 2}


def _to_abbrev(s: str | None) -> str:
    sl = (s or "").strip().lower()
    if len(sl) == 2:
        return sl.upper()
    return _ABBREV.get(sl, s or "")


def select_stores(raw: list[dict], states: list[str] | None, limit: int) -> list[dict]:
    """Pure: flatten redsky store records, keep only allowed states, cap to
    ``limit``. Returns dicts of {store_id, city, state, latitude, longitude}."""
    allowed = {_norm_state(s) for s in states} if states else None
    out: list[dict] = []
    for s in raw:
        sid = s.get("store_id")
        if not sid:
            continue
        addr = s.get("mailing_address") or {}
        state = addr.get("state")
        if allowed is not None and _norm_state(state) not in allowed:
            continue
        geo = s.get("geographic_specifications") or {}
        out.append({
            "store_id": str(sid),
            "city": addr.get("city"),
            "state": state,
            "latitude": geo.get("latitude"),
            "longitude": geo.get("longitude"),
        })
        if len(out) >= limit:
            break
    return out


@register("target_nearby")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    opts = target.options
    tcin = opts.get("tcin")
    if not tcin:
        log.warning("[%s] target_nearby needs options.tcin", target.name)
        return []
    key = opts.get("key") or _DEFAULT_KEY
    zip_code = str(opts.get("zip", "07020"))
    within = int(opts.get("within", 25))
    limit = int(opts.get("limit", 12))
    states = opts.get("states")
    headless = bool(opts.get("headless", False))
    settle_ms = int(opts.get("settle_ms", 6000))
    label = opts.get("label", target.name)

    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        log.warning("[%s] playwright not installed — install \".[browser]\"", target.name)
        return []

    async def _jget(page, url):
        txt = await page.evaluate(
            "async (u) => { const r = await fetch(u, {headers:{'accept':"
            "'application/json'}, credentials:'include'}); return r.ok ? "
            "await r.text() : null; }", url,
        )
        return json.loads(txt) if txt else None

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            ctx = await launch_stealth_persistent_context(
                p, user_data_dir=PROFILE_DIR, user_agent=BROWSER_USER_AGENT,
                headless=headless,
            )
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                # Warm the homepage so the persistent profile's Akamai cookie
                # is in play, then call the JSON endpoints from that context.
                await page.goto(_WARM_URL, wait_until="domcontentloaded")
                await page.wait_for_timeout(settle_ms)
                # 1) resolve nearby stores. nearby_stores_v1 caps `limit` at 20
                # (21+ -> HTTP 400); it returns the *nearest* N, which we then
                # filter to the requested state(s).
                nearby = await _jget(page, f"{_NEARBY}?" + urlencode(
                    {"key": key, "limit": 20, "within": within, "place": zip_code}))
                try:
                    raw = nearby["data"]["nearby_stores"]["stores"]
                except (KeyError, TypeError):
                    log.info("[%s] no nearby_stores (challenged) -> nothing", target.name)
                    return []
                stores = select_stores(raw, states, limit)
                # 2) per-store pickup availability
                observations: list[Observation] = []
                online_data = None
                for st in stores:
                    fp = {
                        "key": key, "tcin": tcin, "store_id": st["store_id"],
                        "zip": zip_code, "state": _to_abbrev(st.get("state")),
                        "latitude": st.get("latitude") or "",
                        "longitude": st.get("longitude") or "",
                        "required_store_id": st["store_id"],
                        "has_required_store_id": "true",
                    }
                    data = await _jget(page, f"{_FULFILLMENT}?{urlencode(fp)}")
                    if data is None:
                        continue
                    if online_data is None:
                        online_data = data  # shipping_options is national
                    status = parse_fulfillment(data, pickup=True)
                    if status is Status.UNKNOWN:
                        continue  # don't write a row we can't read
                    where = ", ".join(filter(None, [st.get("city"), st.get("state")]))
                    observations.append(Observation(
                        key=f"target:{tcin}:store:{st['store_id']}",
                        status=status,
                        title=f"{label} @ {where or st['store_id']}",
                        url=target.url,
                    ))
                # 3) the online (shipping) signal — same key as the old
                # target-etb watcher, enriched with title/price from the PDP.
                if online_data is not None:
                    online_status = parse_fulfillment(online_data, pickup=False)
                    if online_status is not Status.UNKNOWN:
                        otitle, oprice = label, None
                        pdp = await _jget(page, f"{_PDP}?" + urlencode(
                            {"key": key, "tcin": tcin, "pricing_store_id": "1234"}))
                        if pdp is not None:
                            t, pr = parse_pdp(pdp)
                            otitle, oprice = (t or label), pr
                        observations.insert(0, Observation(
                            key=f"target:{tcin}", status=online_status,
                            title=otitle, url=target.url, price=oprice))
            finally:
                await ctx.close()
    except Exception as exc:  # noqa: BLE001 — fail soft on any browser error
        log.warning("[%s] sweep failed: %s", target.name, exc)
        return []

    avail = sum(o.status is Status.IN_STOCK for o in observations)
    log.info("[%s] %d observation(s) (online + NJ pickup), %d available",
             target.name, len(observations), avail)
    return observations
