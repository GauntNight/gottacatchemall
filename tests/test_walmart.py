"""Walmart price-gated availability — the catch is an MSRP-priced offer,
not mere in-stock-ness (the listing is marketplace-only at a markup)."""

from __future__ import annotations

import json

from tcgmon.fetchers.walmart import _item_id, extract_offer, status_from_offer
from tcgmon.models import Status


# ── item id from URL ───────────────────────────────────────────────────────

def test_item_id_from_ip_url():
    assert _item_id(
        "https://www.walmart.com/ip/Pok-mon-TCG-Pitch-Black-Elite-Trainer-Box/20161351456"
    ) == "20161351456"


def test_item_id_strips_query():
    assert _item_id("https://www.walmart.com/ip/slug/123?conditionGroupCode=4") == "123"


# ── price gate (the core decision) ─────────────────────────────────────────

def test_scalper_price_in_stock_reads_out_of_stock():
    # IN_STOCK at $144.77 with an $80 ceiling -> armed (OUT_OF_STOCK), no alert.
    assert status_from_offer("IN_STOCK", 144.77, 80) is Status.OUT_OF_STOCK


def test_msrp_offer_is_in_stock():
    # The catch: an offer at/below the ceiling.
    assert status_from_offer("IN_STOCK", 59.99, 80) is Status.IN_STOCK


def test_price_equal_to_ceiling_is_in_stock():
    assert status_from_offer("IN_STOCK", 80.0, 80) is Status.IN_STOCK


def test_truly_out_of_stock():
    assert status_from_offer("OUT_OF_STOCK", None, 80) is Status.OUT_OF_STOCK
    assert status_from_offer("UNAVAILABLE", None, 80) is Status.OUT_OF_STOCK


def test_in_stock_without_price_is_unknown():
    # In stock but price unreadable -> never guess a buyable signal.
    assert status_from_offer("IN_STOCK", None, 80) is Status.UNKNOWN


def test_unrecognised_status_is_unknown():
    assert status_from_offer("PREORDER_PENDING", 59.99, 80) is Status.UNKNOWN
    assert status_from_offer(None, None, 80) is Status.UNKNOWN


# ── __NEXT_DATA__ extraction ───────────────────────────────────────────────

def _page(product: dict) -> str:
    blob = {"props": {"pageProps": {"initialData": {"data": {"product": product}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(blob)}</script></html>'


def test_extract_offer_canonical():
    html = _page({
        "availabilityStatus": "IN_STOCK",
        "sellerDisplayName": "Revolution Sports Marketing",
        "priceInfo": {"currentPrice": {"price": 144.77, "priceString": "$144.77"}},
    })
    avail, price, seller = extract_offer(html)
    assert avail == "IN_STOCK"
    assert price == 144.77
    assert seller == "Revolution Sports Marketing"


def test_extract_offer_no_island_is_none():
    # Challenge page (no __NEXT_DATA__) -> all None, fetcher maps to UNKNOWN.
    assert extract_offer("<html>px-captcha</html>") == (None, None, None)


def test_extract_offer_missing_product_is_none():
    blob = '<script id="__NEXT_DATA__">{"props":{"pageProps":{"initialData":{"data":{}}}}}</script>'
    assert extract_offer(blob) == (None, None, None)
