"""RedSky JSON parsing — availability from product_fulfillment_v1,
title/price from pdp_client_v1. (The browser fallback is integration-only.)"""

from __future__ import annotations

from tcgmon.fetchers.redsky import parse_fulfillment, parse_pdp
from tcgmon.models import Status


def _fulfillment(status=None, qty=None):
    ship = {}
    if status is not None:
        ship["availability_status"] = status
    if qty is not None:
        ship["available_to_promise_quantity"] = qty
    return {"data": {"product": {"fulfillment": {"shipping_options": ship}}}}


# ── availability ───────────────────────────────────────────────────────────

def test_out_of_stock():
    assert parse_fulfillment(_fulfillment("OUT_OF_STOCK", 0.0)) is Status.OUT_OF_STOCK


def test_in_stock():
    assert parse_fulfillment(_fulfillment("IN_STOCK", 12.0)) is Status.IN_STOCK


def test_preorder_sellable_is_in_stock():
    assert parse_fulfillment(_fulfillment("PRE_ORDER_SELLABLE", 0.0)) is Status.IN_STOCK


def test_quantity_fallback_when_status_unknown():
    assert parse_fulfillment(_fulfillment("MYSTERY", 5.0)) is Status.IN_STOCK
    assert parse_fulfillment(_fulfillment("MYSTERY", 0.0)) is Status.OUT_OF_STOCK


def test_no_signal_is_unknown():
    assert parse_fulfillment(_fulfillment("MYSTERY", None)) is Status.UNKNOWN
    assert parse_fulfillment({"data": {"product": None}}) is Status.UNKNOWN
    assert parse_fulfillment({}) is Status.UNKNOWN


# ── title / price ──────────────────────────────────────────────────────────

def test_pdp_title_unescaped_and_price():
    data = {"data": {"product": {
        "item": {"product_description": {"title": "Pok&#233;mon ETB"}},
        "price": {"formatted_current_price": "$59.99"}}}}
    title, price = parse_pdp(data)
    assert title == "Pokémon ETB"
    assert price == "$59.99"


def test_pdp_missing_is_nones():
    assert parse_pdp({}) == (None, None)
    assert parse_pdp({"data": {"product": {}}}) == (None, None)
