"""Tier 2 / Phase 3 — Walmart via the stealth browser + ``__NEXT_DATA__``.

Walmart runs PerimeterX: plain HTTP returns a captcha page with no
``__NEXT_DATA__`` (verified 2026-06-13), so — like GameStop / Pokémon Center —
we render the product page with the shared stealth browser and read the
embedded JSON island.

**Price gating (important).** The Pitch Black ETB on Walmart is a *marketplace*
listing: the buy box rotates among 3rd-party resellers at a markup (~$145),
with no Walmart-first-party $59.99 offer yet. A plain availability watch is
useless here — it's already IN_STOCK at scalper prices and would never fire.
So we gate on PRICE: the item is a *catch* (IN_STOCK) only when the current
offer is at or below ``options.max_price`` (default $80 — above the $59.99
MSRP, well below the reseller price). It sits OUT_OF_STOCK (armed) at the
scalper price and fires when Walmart — or any seller — lists it near MSRP.

    options:
      max_price: 80         # USD ceiling for an alertable offer
      settle_ms: 6000
      ready_timeout_ms: 20000
      headless: false        # headless is challenged; keep headed

Prereqs:  pip install -e ".[browser]"  &&  playwright install chromium
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlsplit

import httpx

from ..browser import launch_stealth_persistent_context
from ..config import Target
from ..http import BROWSER_USER_AGENT
from ..models import Observation, Status
from .base import register

log = logging.getLogger("tcgmon.walmart")

PROFILE_DIR = ".walmart_profile"
DEFAULT_WARM_URL = "https://www.walmart.com/"
# The JSON island is a <script> — wait for it ATTACHED, never "visible".
READY_SELECTOR = "script#__NEXT_DATA__"
DEFAULT_MAX_PRICE = 80.0

_SCRIPT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
_OUT = ("OUT_OF_STOCK", "UNAVAILABLE", "RETIRED")


def _item_id(url: str) -> str:
    """``/ip/{slug}/{itemId}`` -> ``{itemId}`` (query stripped)."""
    parts = [seg for seg in urlsplit(url).path.split("/") if seg]
    return parts[-1] if parts else url


def extract_offer(html: str):
    """Pull (availabilityStatus, price: float|None, seller: str|None) from the
    rendered page. Uses Walmart's canonical product path; returns (None, …) if
    the island isn't present (challenged) or the product node is missing."""
    m = _SCRIPT_RE.search(html)
    if not m:
        return (None, None, None)
    try:
        blob = json.loads(m.group(1))
    except ValueError:
        return (None, None, None)
    try:
        prod = blob["props"]["pageProps"]["initialData"]["data"]["product"] or {}
    except (KeyError, TypeError):
        return (None, None, None)
    if not prod:
        return (None, None, None)
    avail = prod.get("availabilityStatus")
    seller = prod.get("sellerDisplayName") or prod.get("sellerName")
    cp = (prod.get("priceInfo") or {}).get("currentPrice") or {}
    raw = cp.get("price")
    price = float(raw) if isinstance(raw, (int, float)) else None
    return (avail, price, seller)


def status_from_offer(avail: str | None, price: float | None, max_price: float) -> Status:
    """Price-gated status. IN_STOCK only when a real offer is at/below the
    ceiling — a scalper-priced 'in stock' is treated as OUT_OF_STOCK (armed).
    In stock but no readable price -> UNKNOWN (never guess a buyable signal)."""
    a = (avail or "").upper()
    if a in _OUT:
        return Status.OUT_OF_STOCK
    if a == "IN_STOCK":
        if price is None:
            return Status.UNKNOWN
        return Status.IN_STOCK if price <= max_price else Status.OUT_OF_STOCK
    return Status.UNKNOWN


@register("walmart")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    obs_key = f"walmart:{_item_id(target.url)}"
    unknown = [Observation(key=obs_key, status=Status.UNKNOWN,
                           title=target.name, url=target.url)]

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning(
            "[%s] playwright not installed — `pip install -e \".[browser]\" "
            "&& playwright install chromium`", target.name,
        )
        return unknown

    opts = target.options
    warm_url = opts.get("warm_url", DEFAULT_WARM_URL)
    settle_ms = int(opts.get("settle_ms", 6000))
    ready_timeout_ms = int(opts.get("ready_timeout_ms", 20000))
    headless = bool(opts.get("headless", False))
    max_price = float(opts.get("max_price", DEFAULT_MAX_PRICE))

    try:
        async with async_playwright() as p:
            context = await launch_stealth_persistent_context(
                p, user_data_dir=PROFILE_DIR, user_agent=BROWSER_USER_AGENT,
                headless=headless,
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(warm_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(settle_ms)
                await page.goto(target.url, wait_until="domcontentloaded")
                try:
                    await page.wait_for_selector(READY_SELECTOR, state="attached",
                                                 timeout=ready_timeout_ms)
                except Exception:  # noqa: BLE001 — challenged: island never landed
                    log.info("[%s] __NEXT_DATA__ didn't appear (challenged) -> UNKNOWN",
                             target.name)
                    return unknown
                await page.wait_for_timeout(settle_ms)
                html_text = await page.content()
                name = (await page.title()) or target.name
            finally:
                await context.close()
    except Exception as exc:  # noqa: BLE001 — fail soft on any browser error
        log.warning("[%s] browser fetch failed: %s", target.name, exc)
        return unknown

    avail, price, seller = extract_offer(html_text)
    if avail is None:
        log.info("[%s] no product data in __NEXT_DATA__ -> UNKNOWN", target.name)
        return unknown
    status = status_from_offer(avail, price, max_price)
    price_str = None
    if price is not None:
        price_str = f"${price:.2f}" + (f" — {seller}" if seller else "")
    log.info("[%s] avail=%s price=%s (ceiling $%.0f) -> %s",
             target.name, avail, price, max_price, status.value)

    return [Observation(key=obs_key, status=status,
                        title=name.split(" - Walmart")[0].strip(),
                        url=target.url, price=price_str)]
