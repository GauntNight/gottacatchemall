"""Tier 1 — RSS/Atom feeds (e.g. PokeBeach ``/feed``).

We fetch the feed bytes with our own client (so UA/timeout are controlled)
and hand them to ``feedparser``. Each entry becomes a ``LISTED``
observation keyed by entry id/link, optionally keyword-filtered.
"""

from __future__ import annotations

import logging

import feedparser
import httpx

from ..config import Target
from ..models import Observation, Status
from .base import register

log = logging.getLogger("tcgmon.rss")


@register("rss")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    try:
        resp = await client.get(target.url)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("[%s] fetch failed: %s", target.name, exc)
        return []

    parsed = feedparser.parse(resp.content)
    out: list[Observation] = []
    for entry in parsed.entries:
        title = getattr(entry, "title", "")
        summary = getattr(entry, "summary", "")
        if not target.matches(f"{title} {summary}"):
            continue
        entry_id = getattr(entry, "id", None) or getattr(entry, "link", title)
        out.append(
            Observation(
                key=f"rss:{target.name}:{entry_id}",
                status=Status.LISTED,
                title=title,
                url=getattr(entry, "link", None),
            )
        )
    return out
