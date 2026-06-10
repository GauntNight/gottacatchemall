"""Tier 1 — Reddit listings.

If OAuth credentials are present (``REDDIT_CLIENT_ID`` / ``_CLIENT_SECRET``
/ ``_REFRESH_TOKEN`` — see ``python -m tcgmon.reddit_auth``), we call the
authenticated ``oauth.reddit.com`` API (100 req/min, stable). Otherwise we
fall back to the anonymous ``.json`` endpoint, which Reddit now throttles
and frequently 403s. Either way each matching post becomes a one-time
``LISTED`` observation keyed by its fullname id.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..config import Target
from ..http import REDDIT_USER_AGENT
from ..models import Observation, Status
from .base import register

log = logging.getLogger("tcgmon.reddit")

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"

# Module-level access-token cache, shared across all reddit targets.
_token: dict[str, object] = {"access": None, "expires_at": 0.0}
_token_lock = asyncio.Lock()


def _oauth_configured() -> bool:
    return all(
        os.environ.get(k)
        for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_REFRESH_TOKEN")
    )


def _as_json_url(url: str) -> str:
    """Anonymous endpoint: put ``.json`` on the path, before the query.

    ``.../new?limit=25`` -> ``.../new.json?limit=25``; an already-suffixed
    URL is left untouched.
    """
    parts = urlsplit(url)
    path = parts.path
    if not path.endswith(".json"):
        path = f"{path.rstrip('/')}.json"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _oauth_url(url: str) -> str:
    """OAuth endpoint: same path on ``oauth.reddit.com`` with no ``.json``."""
    parts = urlsplit(url)
    path = parts.path[:-5] if parts.path.endswith(".json") else parts.path
    return urlunsplit(("https", "oauth.reddit.com", path, parts.query, ""))


async def _access_token(client: httpx.AsyncClient) -> str | None:
    """Return a cached access token, refreshing via the refresh token."""
    async with _token_lock:
        now = time.monotonic()
        if _token["access"] and now < float(_token["expires_at"]) - 60:
            return str(_token["access"])
        try:
            resp = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": os.environ["REDDIT_REFRESH_TOKEN"],
                },
                auth=(os.environ["REDDIT_CLIENT_ID"],
                      os.environ["REDDIT_CLIENT_SECRET"]),
                headers={"User-Agent": REDDIT_USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("reddit token refresh failed: %s", exc)
            return None
        _token["access"] = data["access_token"]
        _token["expires_at"] = now + float(data.get("expires_in", 3600))
        return str(_token["access"])


def _matches(title: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    low = title.lower()
    return any(kw.lower() in low for kw in keywords)


async def _get_listing(target: Target, client: httpx.AsyncClient) -> dict | None:
    """Fetch the listing JSON via OAuth if configured, else anonymously."""
    if _oauth_configured():
        token = await _access_token(client)
        if token is None:
            return None
        url = _oauth_url(target.url)
        headers = {"Authorization": f"bearer {token}",
                   "User-Agent": REDDIT_USER_AGENT}
    else:
        url = _as_json_url(target.url)
        headers = {"User-Agent": REDDIT_USER_AGENT}
    try:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("[%s] fetch failed: %s", target.name, exc)
        return None


@register("reddit_json")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    data = await _get_listing(target, client)
    if data is None:
        return []

    out: list[Observation] = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        title = post.get("title", "")
        if not _matches(title, target.keywords):
            continue
        post_id = post.get("name") or post.get("id")  # e.g. t3_abc123
        permalink = post.get("permalink")
        link = (
            f"https://www.reddit.com{permalink}" if permalink else post.get("url")
        )
        out.append(
            Observation(
                key=f"reddit:{post.get('subreddit', '?')}:{post_id}",
                status=Status.LISTED,
                title=title,
                url=link,
            )
        )
    return out
