"""Tier 1 — Reddit via a logged-in headless browser session.

Avoids OAuth app registration entirely: you log in once with
``python -m tcgmon.reddit_login`` (saves a session file), and this fetcher
drives headless Chromium with that session to pull the same listing JSON a
real browser sees — sailing past the 403s that hit raw HTTP clients.

Playwright is imported lazily so the package still loads without the
``browser`` extra installed. If the session file is missing or Playwright
isn't installed, this fails soft (returns no observations) and logs how to
fix it.

Setup:
    pip install -e ".[browser]"   &&   playwright install chromium
    python -m tcgmon.reddit_login
"""

from __future__ import annotations

import json
import logging
import os

import httpx

from ..config import Target
from ..http import BROWSER_USER_AGENT
from ..models import Observation
from .base import register
from .reddit_json import _as_json_url, parse_listing

log = logging.getLogger("tcgmon.reddit_browser")

SESSION_FILE_ENV = "REDDIT_SESSION_FILE"
DEFAULT_SESSION_FILE = ".reddit_session.json"


def session_file() -> str:
    return os.environ.get(SESSION_FILE_ENV, DEFAULT_SESSION_FILE)


@register("reddit_browser")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    path = session_file()
    if not os.path.exists(path):
        log.warning(
            "[%s] no session file at %s — run `python -m tcgmon.reddit_login`",
            target.name, path,
        )
        return []

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning(
            "[%s] playwright not installed — `pip install -e \".[browser]\" "
            "&& playwright install chromium`", target.name,
        )
        return []

    url = _as_json_url(target.url)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    storage_state=path, user_agent=BROWSER_USER_AGENT
                )
                page = await context.new_page()
                resp = await page.goto(url, wait_until="domcontentloaded")
                if resp is None or not resp.ok:
                    code = resp.status if resp else "no-response"
                    log.warning("[%s] browser fetch %s -> %s", target.name, url, code)
                    return []
                body = await resp.text()
            finally:
                await browser.close()
        data = json.loads(body)
    except Exception as exc:  # noqa: BLE001 — fail soft on any browser/parse error
        log.warning("[%s] browser fetch failed: %s", target.name, exc)
        return []

    return parse_listing(data, target)
