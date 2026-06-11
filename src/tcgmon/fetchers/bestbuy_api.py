"""Tier 2 — Best Buy Products API (the one real official API here).

Needs a free API key in ``BESTBUY_API_KEY``. Returns one observation per
SKU using ``onlineAvailability``. No key -> skipped (no observations).

Two watch modes via ``options`` (SKU list preferred for Tier-2):
  - ``skus: [6588509, ...]`` — watch exact SKUs in ONE call via the API's
    ``in()`` operator. Precise and call-efficient; this is the right mode
    once you know the product SKUs.
  - ``search: pokemon elite trainer`` — fuzzy keyword search (defaults to
    the target name). Good for discovery before the SKUs are known.

Rate limits are generous (50k calls/day, 5/sec) — a 5-min poll is ~288/day,
nowhere near the cap. A 403 here means rate-limit-exceeded or a bad key
(distinct from the bot-fingerprint 403s other retailers throw).

Docs / key: https://developer.bestbuy.com
"""

from __future__ import annotations

import logging
import os
from urllib.parse import quote

import httpx

from ..config import Target
from ..models import Observation, Status
from .base import register

log = logging.getLogger("tcgmon.bestbuy")

_FIELDS = "sku,name,onlineAvailability,regularPrice,url"
_BASE = "https://api.bestbuy.com/v1"


def _selector(target: Target) -> str:
    """Build the ``products(...)`` selector — SKU list if given, else search.

    Pure (no API key) so it's unit-testable. The ``in()`` operator batches a
    whole SKU list into a single request (Best Buy's own recommended way to
    avoid calls-per-second errors).
    """
    skus = target.options.get("skus")
    if skus:
        sku_list = ",".join(str(s).strip() for s in skus)
        return f"products(sku in({sku_list}))"
    search = target.options.get("search") or target.name
    return f"products(search={quote(search)})"


@register("bestbuy_api")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    api_key = os.environ.get("BESTBUY_API_KEY", "")
    if not api_key:
        log.warning("[%s] BESTBUY_API_KEY not set; skipping", target.name)
        return []

    url = (
        f"{_BASE}/{_selector(target)}"
        f"?apiKey={api_key}&format=json&pageSize=100&show={_FIELDS}"
    )
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        products = resp.json().get("products", [])
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            log.warning("[%s] 403 — Best Buy rate limit exceeded or invalid "
                        "API key (not a bot block)", target.name)
        else:
            log.warning("[%s] fetch failed: %s", target.name, exc)
        return []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("[%s] fetch failed: %s", target.name, exc)
        return []

    out: list[Observation] = []
    for p in products:
        sku = p.get("sku")
        available = p.get("onlineAvailability")
        price = p.get("regularPrice")
        out.append(
            Observation(
                key=f"bestbuy:{sku}",
                status=Status.IN_STOCK if available else Status.OUT_OF_STOCK,
                title=p.get("name"),
                url=p.get("url"),
                price=f"${price}" if price is not None else None,
            )
        )
    return out
