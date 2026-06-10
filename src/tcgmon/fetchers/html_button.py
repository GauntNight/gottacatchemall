"""Tier 2 / Phase 3 — generic add-to-cart button text scrape.

Last resort for custom storefronts (DA Card World, ToyWiz, GameStop) with
no JSON endpoint. Looks for in-stock / out-of-stock signal phrases in the
rendered HTML. Configure phrases per target via ``options``:

    options:
      in_stock_signals:  ["add to cart", "add to bag"]
      oos_signals:       ["out of stock", "sold out", "notify me"]

Heuristic and brittle by nature -> ambiguous pages resolve to UNKNOWN.
"""

from __future__ import annotations

import logging

import httpx
from selectolax.parser import HTMLParser

from ..config import Target
from ..models import Observation, Status
from .base import register

log = logging.getLogger("tcgmon.html_button")

_DEFAULT_IN = ["add to cart", "add to bag", "buy now"]
_DEFAULT_OOS = ["out of stock", "sold out", "notify me", "unavailable",
                "coming soon"]


@register("html_button")
async def fetch(target: Target, client: httpx.AsyncClient) -> list[Observation]:
    obs_key = f"html:{target.name}"
    unknown = [Observation(key=obs_key, status=Status.UNKNOWN,
                           title=target.name, url=target.url)]
    try:
        resp = await client.get(target.url)
        resp.raise_for_status()
        text = HTMLParser(resp.text).text(separator=" ").lower()
    except httpx.HTTPError as exc:
        log.warning("[%s] fetch failed: %s", target.name, exc)
        return unknown

    oos = [s.lower() for s in target.options.get("oos_signals", _DEFAULT_OOS)]
    in_stock = [s.lower() for s in target.options.get("in_stock_signals", _DEFAULT_IN)]

    has_oos = any(s in text for s in oos)
    has_in = any(s in text for s in in_stock)

    # OOS phrasing wins ties: "notify me" buttons often sit next to a
    # disabled "add to cart", so a present OOS signal is the safer read.
    if has_oos:
        status = Status.OUT_OF_STOCK
    elif has_in:
        status = Status.IN_STOCK
    else:
        status = Status.UNKNOWN

    return [Observation(key=obs_key, status=status, title=target.name,
                        url=target.url)]
