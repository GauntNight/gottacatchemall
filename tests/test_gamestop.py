"""GameStop availability parsing — JSON-LD first, text-signal fallback."""

from __future__ import annotations

from tcgmon.fetchers.gamestop import (
    _product_id,
    status_from_jsonld,
    status_from_text,
    _DEFAULT_IN,
    _DEFAULT_OOS,
)
from tcgmon.models import Status


# ── product id from URL ────────────────────────────────────────────────────

def test_product_id_strips_html_suffix():
    assert _product_id(
        "https://www.gamestop.com/toys-games/trading-cards/products/"
        "pokemon-trading-card-game-pitch-black-elite-trainer-box/20034819.html"
    ) == "20034819"


def test_product_id_handles_trailing_slash():
    assert _product_id("https://www.gamestop.com/products/foo/12345/") == "12345"


# ── JSON-LD availability ───────────────────────────────────────────────────

def test_jsonld_instock():
    html = '<script type="application/ld+json">{"offers":{"availability":"https://schema.org/InStock"}}</script>'
    assert status_from_jsonld(html) is Status.IN_STOCK


def test_jsonld_preorder_is_in_stock():
    # A live preorder is buyable -> IN_STOCK (the edge we want to catch).
    html = '{"availability": "http://schema.org/PreOrder"}'
    assert status_from_jsonld(html) is Status.IN_STOCK


def test_jsonld_outofstock():
    html = '{"availability":"https://schema.org/OutOfStock"}'
    assert status_from_jsonld(html) is Status.OUT_OF_STOCK


def test_jsonld_oos_wins_ties():
    # Mixed offers (e.g. ship vs in-store) -> safer to read as OOS than to
    # fire a false in-stock alert.
    html = ('{"availability":"https://schema.org/InStock"}'
            '{"availability":"https://schema.org/OutOfStock"}')
    assert status_from_jsonld(html) is Status.OUT_OF_STOCK


def test_jsonld_absent_returns_none():
    # No availability token -> let the caller fall back to text.
    assert status_from_jsonld("<html><body>no schema here</body></html>") is None


# ── text-signal fallback ───────────────────────────────────────────────────

def test_text_add_to_cart_is_in_stock():
    assert status_from_text("Pitch Black ETB — Add to Cart",
                            _DEFAULT_IN, _DEFAULT_OOS) is Status.IN_STOCK


def test_text_sold_out_is_out_of_stock():
    assert status_from_text("Sold Out — Notify Me",
                            _DEFAULT_IN, _DEFAULT_OOS) is Status.OUT_OF_STOCK


def test_text_oos_wins_when_both_present():
    assert status_from_text("Add to Cart but Coming Soon",
                            _DEFAULT_IN, _DEFAULT_OOS) is Status.OUT_OF_STOCK


def test_text_no_signal_is_unknown():
    assert status_from_text("just some page text",
                            _DEFAULT_IN, _DEFAULT_OOS) is Status.UNKNOWN
