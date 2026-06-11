"""Tier 2 / Phase 3 — Pokémon Center category watcher (official MSRP source).

PC is the hardest target on the list: Akamai Bot Manager challenges
automation, and the site queues during drops (it fell over from human
traffic alone on 2026-06-10). So we do NOT hammer product pages — we poll a
*category* page and watch for new product tiles appearing. A new SKU showing
up in the category is the drop / preorder-opening signal, which is exactly
what edge detection wants (absent -> listed).

Hard-won mechanics, learned by probing the live site:
  - Headless is reliably detected (0 tiles). We run *headed* real Chrome.
  - A persistent profile + a homepage warm-up lets Akamai's sensor cookie
    validate, which raises the success rate across repeated polls.
  - The category navigation often returns HTTP 403 while the SPA still
    renders the tiles. So SUCCESS is defined by tiles appearing in the DOM,
    NOT by the response status.
  - Detection is probabilistic. When challenged, no tiles render — we then
    observe *nothing* (empty), never a stock signal. No false alerts.

Each rendered tile becomes a LISTED observation keyed by its SKU and run
through the target's keyword filter, so adding the next set is just editing
``keywords`` / ``require`` in targets.yaml.

Config:
    - name: pokecenter-etb
      fetcher: pokemoncenter
      url: https://www.pokemoncenter.com/category/elite-trainer-box
      interval_minutes: 12
      keywords: [pitch black, "elite trainer"]   # optional title filter
      options:
        warm_url: https://www.pokemoncenter.com/   # default
        settle_ms: 7000                            # homepage warm-up wait
        tiles_timeout_ms: 15000                    # how long to wait for tiles
        headless: false                            # headless is detected; keep headed

Prereqs:  pip install -e ".[browser]"  &&  playwright install chromium
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urljoin, urlsplit

import httpx

from ..browser import launch_stealth_persistent_context
from ..config import Target
from ..http import BROWSER_USER_AGENT
from ..models import Observation, Status
from .base import register

log = logging.getLogger("tcgmon.pokemoncenter")

PROFILE_DIR = os.environ.get("PC_PROFILE_DIR", ".pc_profile")
TILE_SELECTOR = "a[href*='/product/']"
DEFAULT_WARM_URL = "https://www.pokemoncenter.com/"


def _sku_from_href(href: str) -> str:
    """``/product/{sku}/{slug}`` -> ``{sku}``; unknown shapes -> the href."""
    parts = [seg for seg in urlsplit(href).path.split("/") if seg]
    if "product" in parts:
        i = parts.index("product")
        if i + 1 < len(parts):
            return parts[i + 1]
    return href


@register("pokemoncenter")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning(
            "[%s] playwright not installed — `pip install -e \".[browser]\" "
            "&& playwright install chromium`", target.name,
        )
        return []

    opts = target.options
    warm_url = opts.get("warm_url", DEFAULT_WARM_URL)
    settle_ms = int(opts.get("settle_ms", 7000))
    tiles_timeout_ms = int(opts.get("tiles_timeout_ms", 15000))
    headless = bool(opts.get("headless", False))

    try:
        async with async_playwright() as p:
            context = await launch_stealth_persistent_context(
                p, user_data_dir=PROFILE_DIR, user_agent=BROWSER_USER_AGENT,
                headless=headless,
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                # Warm the homepage so Akamai's sensor cookie validates.
                await page.goto(warm_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(settle_ms)
                # Status is unreliable (often 403 while the SPA still renders);
                # we judge success by whether tiles actually appear.
                await page.goto(target.url, wait_until="domcontentloaded")
                try:
                    await page.wait_for_selector(TILE_SELECTOR, timeout=tiles_timeout_ms)
                except Exception:  # noqa: BLE001 — challenged: no tiles rendered
                    log.info("[%s] no product tiles (challenged) -> nothing observed",
                             target.name)
                    return []
                tiles = await page.eval_on_selector_all(
                    TILE_SELECTOR,
                    "els => els.map(e => ({href: e.getAttribute('href'),"
                    " txt: (e.innerText || e.textContent || '')"
                    ".replace(/\\s+/g, ' ').trim()}))",
                )
            finally:
                await context.close()
    except Exception as exc:  # noqa: BLE001 — fail soft on any browser error
        log.warning("[%s] browser fetch failed: %s", target.name, exc)
        return []

    # De-dupe by SKU (the grid can repeat a product across links), filter by
    # keywords, and emit one LISTED observation per distinct product.
    out: list[Observation] = []
    seen: set[str] = set()
    for tile in tiles:
        href = tile.get("href") or ""
        title = tile.get("txt") or ""
        if not href or not target.matches(title):
            continue
        sku = _sku_from_href(href)
        if sku in seen:
            continue
        seen.add(sku)
        out.append(
            Observation(
                key=f"pokecenter:{sku}",
                status=Status.LISTED,
                title=title or sku,
                url=urljoin("https://www.pokemoncenter.com", href),
            )
        )
    log.info("[%s] %d product tile(s) observed", target.name, len(out))
    return out
