"""Tier 2 — Best Buy Products API (the one real official API here).

Needs a free API key in ``BESTBUY_API_KEY``. ``target.options['search']``
is the search expression (defaults to the target name). Returns one
observation per SKU using ``onlineAvailability``. No key -> UNKNOWN.

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


@register("bestbuy_api")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    api_key = os.environ.get("BESTBUY_API_KEY", "")
    if not api_key:
        log.warning("[%s] BESTBUY_API_KEY not set; skipping", target.name)
        return []

    search = target.options.get("search") or target.name
    url = (
        f"https://api.bestbuy.com/v1/products(search={quote(search)})"
        f"?apiKey={api_key}&format=json&pageSize=25&show={_FIELDS}"
    )
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        products = resp.json().get("products", [])
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
