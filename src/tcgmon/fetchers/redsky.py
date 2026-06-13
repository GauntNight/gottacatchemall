"""Tier 2 / Phase 3 — Target via the unofficial RedSky API.

RedSky is undocumented and drifts without notice, so this fetcher is
best-effort: anything unexpected -> UNKNOWN, never an exception.

Discovered live (2026-06-12) for the Pitch Black ETB (TCIN 1011483406):

* The ``key`` is a *static, public* web key baked into target.com's
  frontend — the same for every shopper. We ship a known-good default
  so the watcher works out of the box; override via ``options.key`` if
  it ever rotates.
* Availability is NOT in ``pdp_client_v1`` (its ``fulfillment`` is null)
  and the old ``pdp_fulfillment_v1`` endpoint is now ``410 Gone``. Stock
  lives in ``product_fulfillment_v1``, which needs a location. Online
  drops surface under ``fulfillment.shipping_options.availability_status``
  (national, so the exact lat/long barely matters). We read that for the
  edge signal and enrich title/price from ``pdp_client_v1`` best-effort.

    options:
      tcin: "1011483406"      # required (the A-<tcin> in the product URL)
      key:  "<public_web_key>"  # optional; defaults to the shipped key
      store_id: "1234"          # optional location context
      zip: "10001"              # optional
      state: "NY"               # optional
      latitude: "40.71"         # optional
      longitude: "-74.00"       # optional
"""

from __future__ import annotations

import html
import logging

import httpx

from ..config import Target
from ..models import Observation, Status
from .base import register

log = logging.getLogger("tcgmon.redsky")

_BASE = "https://redsky.target.com/redsky_aggregations/v1/web"
_FULFILLMENT = f"{_BASE}/product_fulfillment_v1"
_PDP = f"{_BASE}/pdp_client_v1"

# Long-standing public web key baked into target.com's frontend. Public by
# design (it ships in the page JS); override via options.key if it rotates.
_DEFAULT_KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"

# RedSky/Akamai reject the default httpx UA. A normal browser UA + Target
# origin is enough for these JSON aggregations (no full TLS spoof needed).
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": "https://www.target.com",
    "Referer": "https://www.target.com/",
}

# shipping_options.availability_status string -> our three-valued Status.
_IN = {"IN_STOCK", "AVAILABLE", "PRE_ORDER_SELLABLE", "PRE_ORDER", "LIMITED_STOCK"}
_OUT = {"OUT_OF_STOCK", "UNAVAILABLE", "NOT_AVAILABLE"}


@register("redsky")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    tcin = target.options.get("tcin")
    key = target.options.get("key") or _DEFAULT_KEY
    obs_key = f"target:{tcin or target.name}"
    unknown = [Observation(key=obs_key, status=Status.UNKNOWN,
                           title=target.name, url=target.url)]

    if not tcin:
        log.warning("[%s] redsky needs options.tcin (the A-<tcin> in the URL)", target.name)
        return unknown

    # --- availability (the edge signal) — product_fulfillment_v1 ----------
    params = {
        "key": key,
        "tcin": tcin,
        "store_id": target.options.get("store_id", "1234"),
        "zip": target.options.get("zip", "10001"),
        "state": target.options.get("state", "NY"),
        "latitude": target.options.get("latitude", "40.71"),
        "longitude": target.options.get("longitude", "-74.00"),
        "required_store_id": target.options.get("store_id", "1234"),
        "has_required_store_id": "true",
    }
    try:
        resp = await client.get(_FULFILLMENT, params=params, headers=_HEADERS)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("[%s] fulfillment fetch failed: %s", target.name, exc)
        return unknown

    try:
        fulfillment = (data["data"]["product"] or {}).get("fulfillment") or {}
        ship = fulfillment.get("shipping_options") or {}
        status_str = (ship.get("availability_status") or "").upper()
        qty = ship.get("available_to_promise_quantity")
        if status_str in _IN:
            status = Status.IN_STOCK
        elif status_str in _OUT:
            status = Status.OUT_OF_STOCK
        elif isinstance(qty, (int, float)):
            # Recognised-shape fallback: a real numeric ATP quantity is a
            # trustworthy signal even if the status string drifts.
            status = Status.IN_STOCK if qty > 0 else Status.OUT_OF_STOCK
        else:
            status = Status.UNKNOWN
    except (KeyError, TypeError) as exc:
        log.warning("[%s] unexpected fulfillment shape: %s", target.name, exc)
        return unknown

    # --- enrichment (title + price) — pdp_client_v1, best-effort ----------
    title, price = target.name, None
    try:
        pdp = await client.get(_PDP, params={"key": key, "tcin": tcin,
                                             "pricing_store_id": target.options.get("store_id", "1234")},
                               headers=_HEADERS)
        if pdp.status_code == 200:
            product = pdp.json()["data"]["product"]
            item = product.get("item", {})
            raw_title = (item.get("product_description") or {}).get("title")
            if raw_title:
                title = html.unescape(raw_title)
            price = (product.get("price") or {}).get("formatted_current_price") or price
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        log.debug("[%s] pdp enrichment skipped: %s", target.name, exc)

    return [Observation(key=obs_key, status=status, title=title,
                        url=target.url, price=price)]
