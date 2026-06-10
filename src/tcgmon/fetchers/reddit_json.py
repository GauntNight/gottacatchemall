"""Tier 1 — Reddit JSON listings.

Append ``.json`` to any subreddit listing and parse
``data.children[].data``. Reddit blocks default library UAs, so we send a
descriptive one. Each post becomes a ``LISTED`` observation keyed by its
fullname id, so a matching post alerts exactly once.
"""

from __future__ import annotations

import logging

import httpx

from ..config import Target
from ..http import REDDIT_USER_AGENT
from ..models import Observation, Status
from .base import register

log = logging.getLogger("tcgmon.reddit")


def _matches(title: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    low = title.lower()
    return any(kw.lower() in low for kw in keywords)


@register("reddit_json")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    url = target.url if target.url.endswith(".json") else f"{target.url}.json"
    try:
        resp = await client.get(url, headers={"User-Agent": REDDIT_USER_AGENT})
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("[%s] fetch failed: %s", target.name, exc)
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
