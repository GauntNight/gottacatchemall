"""Pokémon Center SKU extraction from product hrefs."""

from __future__ import annotations

from tcgmon.fetchers.pokemoncenter import _sku_from_href


def test_extracts_sku_from_product_path():
    assert _sku_from_href("/product/123-45-678/pokemon-tcg-etb") == "123-45-678"


def test_handles_absolute_url():
    assert _sku_from_href(
        "https://www.pokemoncenter.com/product/999/slug") == "999"


def test_trailing_slug_optional():
    assert _sku_from_href("/product/abc") == "abc"


def test_unknown_shape_falls_back_to_href():
    assert _sku_from_href("/category/elite-trainer-box") == \
        "/category/elite-trainer-box"
