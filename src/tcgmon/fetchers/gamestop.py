"""Tier 2 / Phase 3 — GameStop product availability via the stealth browser.

GameStop runs on Salesforce Commerce behind a bot wall: plain HTTP 403s
(verified 2026-06-12), so we render the product page with the shared stealth
browser — same approach as Pokémon Center — and read availability from the
rendered DOM. Two signals, cleanest first:

  1. **JSON-LD** ``<script type="application/ld+json">`` → ``offers.availability``
     (schema.org ``InStock`` / ``OutOfStock`` / ``PreOrder`` / ``SoldOut``).
     Structured and stable.
  2. **Button / text signals** as a fallback (Add to Cart / Pre-Order vs Sold
     Out / Not Available / Coming Soon), overridable per target.

Unlike the PC *category* watcher, this tracks ONE product's stock state, so it
emits OUT_OF_STOCK / IN_STOCK and fails soft to **UNKNOWN** (never empty) — a
bot challenge must not overwrite a known state or invent a signal.

Config:
    - name: gamestop-pitch-black
      fetcher: gamestop
      url: https://www.gamestop.com/.../20034819.html
      interval_minutes: 12
      options:
        settle_ms: 4000           # wait after nav for the SPA/JSON-LD to land
        ready_timeout_ms: 15000   # how long to wait for the product area
        headless: false           # headless is detected; keep headed
        in_stock_signals: [...]   # optional overrides
        oos_signals:       [...]

Prereqs:  pip install -e ".[browser]"  &&  playwright install chromium
"""

from __future__ import annotations

import logging
import os
import re
from urllib.parse import urlsplit

import httpx

from ..browser import launch_stealth_persistent_context
from ..config import Target
from ..http import BROWSER_USER_AGENT
from ..models import Observation, Status
from .base import register

log = logging.getLogger("tcgmon.gamestop")

PROFILE_DIR = os.environ.get("GAMESTOP_PROFILE_DIR", ".gamestop_profile")
DEFAULT_WARM_URL = "https://www.gamestop.com/"
# The JSON-LD payload carries availability. It's a <script>, so it is never
# "visible" — we wait for it ATTACHED to the DOM, not visible.
READY_SELECTOR = "script[type='application/ld+json']"

_DEFAULT_IN = ["add to cart", "add to bag", "pre-order", "preorder", "buy now"]
_DEFAULT_OOS = ["sold out", "out of stock", "not available", "unavailable",
                "coming soon", "notify me"]

# schema.org availability tokens (compared lowercased, schema URL stripped).
_AVAIL_IN = ("instock", "preorder", "limitedavailability", "onlineonly",
             "instoreonly", "backorder", "presale")
_AVAIL_OUT = ("outofstock", "soldout", "discontinued")
_AVAIL_RE = re.compile(r'"availability"\s*:\s*"([^"]+)"', re.IGNORECASE)


def _product_id(url: str) -> str:
    """``…/pokemon-…-elite-trainer-box/20034819.html`` -> ``20034819``."""
    last = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    return last[:-5] if last.endswith(".html") else last or url


def status_from_jsonld(html_text: str) -> Status | None:
    """Read ``offers.availability`` tokens out of the rendered HTML.

    Returns None if no availability token is present (so the caller can fall
    back to text). OOS wins ties: a page with mixed offers is the safer read
    as out-of-stock than to fire a false in-stock alert.
    """
    tokens = [m.rsplit("/", 1)[-1].lower() for m in _AVAIL_RE.findall(html_text)]
    if not tokens:
        return None
    if any(t in _AVAIL_OUT for t in tokens):
        return Status.OUT_OF_STOCK
    if any(t in _AVAIL_IN for t in tokens):
        return Status.IN_STOCK
    return Status.UNKNOWN


def status_from_text(text: str, in_signals: list[str], oos_signals: list[str]) -> Status:
    """Heuristic signal-phrase read of the rendered page text. OOS wins ties
    (a disabled 'Add to Cart' often sits next to a 'Notify Me')."""
    low = text.lower()
    if any(s in low for s in oos_signals):
        return Status.OUT_OF_STOCK
    if any(s in low for s in in_signals):
        return Status.IN_STOCK
    return Status.UNKNOWN


@register("gamestop")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    obs_key = f"gamestop:{_product_id(target.url)}"
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
    settle_ms = int(opts.get("settle_ms", 4000))
    ready_timeout_ms = int(opts.get("ready_timeout_ms", 15000))
    headless = bool(opts.get("headless", False))
    in_sigs = [s.lower() for s in opts.get("in_stock_signals", _DEFAULT_IN)]
    oos_sigs = [s.lower() for s in opts.get("oos_signals", _DEFAULT_OOS)]

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
                # Status is unreliable behind the bot wall (403 while the SPA
                # still renders); judge by whether the product area appears.
                await page.goto(target.url, wait_until="domcontentloaded")
                # Wait for the JSON-LD to land in the DOM (attached, not visible
                # — a <script> never becomes visible, which is why a plain
                # wait_for_selector here always timed out and false-flagged a
                # challenge). Best-effort: if it never lands we still parse what
                # rendered and fall through to UNKNOWN naturally below.
                try:
                    await page.wait_for_selector(READY_SELECTOR, state="attached",
                                                 timeout=ready_timeout_ms)
                except Exception:  # noqa: BLE001
                    log.info("[%s] JSON-LD didn't appear in %dms; parsing rendered DOM",
                             target.name, ready_timeout_ms)
                await page.wait_for_timeout(settle_ms)
                html_text = await page.content()
                body_text = await page.eval_on_selector(
                    "body", "el => el.innerText || el.textContent || ''"
                )
                title = (await page.title()) or target.name
            finally:
                await context.close()
    except Exception as exc:  # noqa: BLE001 — fail soft on any browser error
        log.warning("[%s] browser fetch failed: %s", target.name, exc)
        return unknown

    status = status_from_jsonld(html_text)
    source = "json-ld"
    if status in (None, Status.UNKNOWN):
        status = status_from_text(body_text, in_sigs, oos_sigs)
        source = "text-signal"
    if status is Status.UNKNOWN and "application/ld+json" not in html_text:
        log.info("[%s] page didn't render the product (likely challenged) -> UNKNOWN",
                 target.name)
    else:
        log.info("[%s] %s -> %s", target.name, source, status.value)

    return [Observation(key=obs_key, status=status, title=title.strip(),
                        url=target.url)]
