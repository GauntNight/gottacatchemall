"""Tier 1 — Reddit via a headless browser (no login required).

Raw HTTP clients get a flat 403 from Reddit regardless of User-Agent — it
fingerprints the TLS/HTTP stack, not just the UA. A real browser engine
sails past that. So this fetcher drives headless Chromium to pull the same
listing JSON a logged-out browser sees.

The trick Reddit plays: hitting ``.json`` *cold* still 403s, but once the
context has loaded a normal HTML listing page (which sets the session
cookies a browser would have), the ``.json`` endpoint returns clean JSON.
So we warm the context on the ``old.reddit.com`` HTML page first, then
fetch the JSON. ``old.reddit.com`` is used throughout because it serves
real server-rendered HTML (and JSON) rather than the heavy React shell.

A logged-in session file (from ``python -m tcgmon.reddit_login``) is used
*if present* — it raises the rate ceiling and unlocks gated subs — but it
is no longer required: anonymous browser access is enough for public subs.

Playwright is imported lazily so the package still loads without the
``browser`` extra. If Playwright isn't installed this fails soft (returns
no observations) and logs how to fix it.

Setup:
    pip install -e ".[browser]"   &&   playwright install chromium
    # optional, for higher limits / gated subs:
    python -m tcgmon.reddit_login
"""

from __future__ import annotations

import json
import logging
import os
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..config import Target
from ..http import BROWSER_USER_AGENT
from ..models import Observation
from .base import register
from .reddit_json import _as_json_url, parse_listing

log = logging.getLogger("tcgmon.reddit_browser")

SESSION_FILE_ENV = "REDDIT_SESSION_FILE"
DEFAULT_SESSION_FILE = ".reddit_session.json"

OLD_REDDIT = "old.reddit.com"


def session_file() -> str:
    return os.environ.get(SESSION_FILE_ENV, DEFAULT_SESSION_FILE)


def _on_old_reddit(url: str) -> str:
    """Rehost a reddit URL on ``old.reddit.com`` (server-rendered)."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme or "https", OLD_REDDIT, parts.path,
                       parts.query, parts.fragment))


def _warm_url(json_url: str) -> str:
    """The HTML listing page for a ``.json`` URL — visited to set cookies."""
    parts = urlsplit(json_url)
    path = parts.path[:-5] if parts.path.endswith(".json") else parts.path
    # No query (limit etc. is JSON-only) — just the human listing page.
    return urlunsplit((parts.scheme, parts.netloc, path.rstrip("/") + "/", "", ""))


@register("reddit_browser")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning(
            "[%s] playwright not installed — `pip install -e \".[browser]\" "
            "&& playwright install chromium`", target.name,
        )
        return []

    json_url = _on_old_reddit(_as_json_url(target.url))
    warm_url = _warm_url(json_url)

    # Use a saved login session if one exists; otherwise go anonymous.
    path = session_file()
    storage_state = path if os.path.exists(path) else None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    storage_state=storage_state, user_agent=BROWSER_USER_AGENT
                )
                page = await context.new_page()
                # Warm the context: a cold .json hit 403s, but after loading
                # the HTML listing page the .json endpoint returns JSON.
                await page.goto(warm_url, wait_until="domcontentloaded")
                resp = await page.goto(json_url, wait_until="domcontentloaded")
                if resp is None or not resp.ok:
                    code = resp.status if resp else "no-response"
                    log.warning("[%s] browser fetch %s -> %s",
                                target.name, json_url, code)
                    return []
                body = await resp.text()
            finally:
                await browser.close()
        data = json.loads(body)
    except Exception as exc:  # noqa: BLE001 — fail soft on any browser/parse error
        log.warning("[%s] browser fetch failed: %s", target.name, exc)
        return []

    return parse_listing(data, target)
