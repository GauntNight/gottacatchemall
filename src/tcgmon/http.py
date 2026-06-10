"""Shared async HTTP client, User-Agent rotation, and jitter helpers.

Design rule #3: jitter everything and rotate realistic browser UAs. One
source failing must not block others, so every fetch runs under a tight
per-request timeout.
"""

from __future__ import annotations

import random

import httpx

# A small pool of realistic, current-ish desktop browser User-Agents.
# Bot-protected sites reject obvious bot/library UAs outright.
USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
    "Gecko/20100101 Firefox/126.0",
]

# Reddit blocks default library UAs; it wants something descriptive.
REDDIT_USER_AGENT = "gottacatchemall-tcg-monitor/0.1 (personal restock watcher)"

# Used by the browser-session path (reddit_login + reddit_browser) so the
# saved session and the polling context present the same UA.
BROWSER_USER_AGENT = USER_AGENTS[0]

DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=10.0)


def random_user_agent() -> str:
    return random.choice(USER_AGENTS)


def jittered(interval_seconds: float, spread: float = 0.3) -> float:
    """Return ``interval * uniform(1-spread, 1+spread)`` (design rule #3)."""
    factor = random.uniform(1.0 - spread, 1.0 + spread)
    return interval_seconds * factor


def make_client(headers: dict[str, str] | None = None) -> httpx.AsyncClient:
    """Build an async client with browser-ish defaults and redirects on."""
    base_headers = {
        "User-Agent": random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        base_headers.update(headers)
    return httpx.AsyncClient(
        headers=base_headers,
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    )
