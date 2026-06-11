"""Shopify .js endpoint helpers — URL normalization and cents pricing."""

from __future__ import annotations

from tcgmon.fetchers.shopify_json import _format_price, _js_url


def test_js_url_appends_js():
    assert _js_url("https://x.com/products/abc") == "https://x.com/products/abc.js"


def test_js_url_replaces_json_suffix():
    assert _js_url("https://x.com/products/abc.json") == "https://x.com/products/abc.js"


def test_js_url_idempotent_on_js():
    assert _js_url("https://x.com/products/abc.js") == "https://x.com/products/abc.js"


def test_js_url_strips_trailing_slash():
    assert _js_url("https://x.com/products/abc/") == "https://x.com/products/abc.js"


def test_format_price_cents_to_dollars():
    assert _format_price(4999) == "$49.99"
    assert _format_price(11495) == "$114.95"


def test_format_price_handles_missing():
    assert _format_price(None) is None
