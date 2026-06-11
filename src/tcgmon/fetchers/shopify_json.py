"""Tier 2 — Shopify storefront product JSON (the ``.js`` AJAX endpoint).

Shopify exposes ``{product_url}.js`` — the storefront AJAX API — returning
the product as JSON with a per-variant ``available`` boolean and price in
**integer cents**. We use ``.js`` rather than the sibling ``.json``
because many storefronts omit ``available`` from ``.json`` (every variant
then looks out-of-stock and the watcher never fires). Any available variant
-> IN_STOCK, else OUT_OF_STOCK. Network/parse trouble -> UNKNOWN (fail soft,
design rule #2).

The registered name stays ``shopify_json`` for config compatibility.
"""

from __future__ import annotations

import logging

import httpx

from ..config import Target
from ..models import Observation, Status
from .base import register

log = logging.getLogger("tcgmon.shopify")


def _js_url(url: str) -> str:
    """Normalize a product URL to its ``.js`` AJAX endpoint."""
    for suffix in (".js", ".json"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return f"{url.rstrip('/')}.js"


def _format_price(cents: object) -> str | None:
    """Shopify ``.js`` prices are integer cents -> ``$49.99``."""
    if isinstance(cents, (int, float)):
        return f"${cents / 100:.2f}"
    return None


@register("shopify_json")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    url = _js_url(target.url)
    unknown = [Observation(key=f"shopify:{target.name}", status=Status.UNKNOWN,
                           title=target.name, url=target.url)]
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        product = resp.json()  # .js returns the product object at top level
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("[%s] fetch failed: %s", target.name, exc)
        return unknown

    variants = product.get("variants", [])
    if not variants:
        return unknown

    available = any(v.get("available") for v in variants)
    return [
        Observation(
            key=f"shopify:{target.name}",
            status=Status.IN_STOCK if available else Status.OUT_OF_STOCK,
            title=product.get("title") or target.name,
            url=target.url,
            price=_format_price(variants[0].get("price")),
        )
    ]
