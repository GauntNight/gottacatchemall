"""Tier 2 — Shopify storefront product JSON.

Shopify stores expose ``{product_url}.json`` with ``variants[].available``.
If any variant is available -> IN_STOCK, otherwise OUT_OF_STOCK. Network or
parse trouble -> UNKNOWN (fail soft, design rule #2).
"""

from __future__ import annotations

import logging

import httpx

from ..config import Target
from ..models import Observation, Status
from .base import register

log = logging.getLogger("tcgmon.shopify")


@register("shopify_json")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    url = target.url if target.url.endswith(".json") else f"{target.url}.json"
    unknown = [Observation(key=f"shopify:{target.name}", status=Status.UNKNOWN,
                           title=target.name, url=target.url)]
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        product = resp.json().get("product", {})
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("[%s] fetch failed: %s", target.name, exc)
        return unknown

    variants = product.get("variants", [])
    if not variants:
        return unknown

    available = any(v.get("available") for v in variants)
    price = variants[0].get("price")
    return [
        Observation(
            key=f"shopify:{target.name}",
            status=Status.IN_STOCK if available else Status.OUT_OF_STOCK,
            title=product.get("title") or target.name,
            url=target.url,
            price=f"${price}" if price else None,
        )
    ]
