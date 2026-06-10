"""Tier 2 / Phase 3 — Walmart via the embedded ``__NEXT_DATA__`` blob.

Walmart product pages are Next.js and embed a JSON island in
``<script id="__NEXT_DATA__">`` containing availability. Walmart runs
PerimeterX, so expect challenges — anything unexpected -> UNKNOWN.

The exact JSON path drifts, so we search the blob for an
``availabilityStatus`` value rather than hard-coding the full path.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from ..config import Target
from ..models import Observation, Status
from .base import register

log = logging.getLogger("tcgmon.nextdata")

_SCRIPT_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


def _find_availability(node: object) -> str | None:
    """Walk the decoded JSON looking for the first availabilityStatus."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "availabilityStatus" and isinstance(v, str):
                return v
            found = _find_availability(v)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_availability(item)
            if found:
                return found
    return None


@register("nextdata")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    obs_key = f"walmart:{target.name}"
    unknown = [Observation(key=obs_key, status=Status.UNKNOWN,
                           title=target.name, url=target.url)]
    try:
        resp = await client.get(target.url)
        resp.raise_for_status()
        html = resp.text
    except httpx.HTTPError as exc:
        log.warning("[%s] fetch failed: %s", target.name, exc)
        return unknown

    match = _SCRIPT_RE.search(html)
    if not match:
        log.info("[%s] no __NEXT_DATA__ (challenged?) -> unknown", target.name)
        return unknown

    try:
        blob = json.loads(match.group(1))
    except ValueError:
        return unknown

    status_str = (_find_availability(blob) or "").upper()
    if status_str == "IN_STOCK":
        status = Status.IN_STOCK
    elif status_str in ("OUT_OF_STOCK", "UNAVAILABLE"):
        status = Status.OUT_OF_STOCK
    else:
        status = Status.UNKNOWN

    return [Observation(key=obs_key, status=status, title=target.name,
                        url=target.url)]
