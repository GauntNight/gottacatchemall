"""Tier 2 / Phase 3 — Target via the unofficial RedSky API.

RedSky is undocumented and can change without notice, so this fetcher is
best-effort: anything unexpected -> UNKNOWN. Provide the TCIN and the
public web ``key`` (visible in browser devtools on any product page) via
``target.options``:

    options:
      tcin: "1004012345"
      key:  "<public_web_key>"
      store_id: "1234"   # optional, for fulfillment context
"""

from __future__ import annotations

import logging

import httpx

from ..config import Target
from ..models import Observation, Status
from .base import register

log = logging.getLogger("tcgmon.redsky")

_ENDPOINT = "https://redsky.target.com/redsky_aggregations/v1/web/pdp_client_v1"


@register("redsky")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    tcin = target.options.get("tcin")
    key = target.options.get("key")
    obs_key = f"target:{tcin or target.name}"
    unknown = [Observation(key=obs_key, status=Status.UNKNOWN,
                           title=target.name, url=target.url)]

    if not (tcin and key):
        log.warning("[%s] redsky needs options.tcin and options.key", target.name)
        return unknown

    params = {"key": key, "tcin": tcin, "pricing_store_id": target.options.get("store_id", "1234")}
    try:
        resp = await client.get(_ENDPOINT, params=params)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("[%s] fetch failed: %s", target.name, exc)
        return unknown

    # RedSky's shape drifts; dig defensively.
    try:
        product = data["data"]["product"]
        item = product.get("item", {})
        title = (item.get("product_description") or {}).get("title") or target.name
        # Availability lives under fulfillment/shipping; treat anything we
        # don't recognise as UNKNOWN rather than guessing.
        ship = (product.get("fulfillment") or {}).get("shipping_options") or {}
        status_str = (ship.get("availability_status") or "").upper()
        if status_str in ("IN_STOCK", "AVAILABLE", "PRE_ORDER_SELLABLE"):
            status = Status.IN_STOCK
        elif status_str in ("OUT_OF_STOCK", "UNAVAILABLE"):
            status = Status.OUT_OF_STOCK
        else:
            status = Status.UNKNOWN
        price = (product.get("price") or {}).get("formatted_current_price")
    except (KeyError, TypeError) as exc:
        log.warning("[%s] unexpected redsky shape: %s", target.name, exc)
        return unknown

    return [Observation(key=obs_key, status=status, title=title,
                        url=target.url, price=price)]
