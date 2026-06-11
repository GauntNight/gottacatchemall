"""Best Buy selector building — SKU `in()` batch vs fuzzy search."""

from __future__ import annotations

from tcgmon.config import Target
from tcgmon.fetchers.bestbuy_api import _selector


def _t(**opts) -> Target:
    return Target(name="bb", fetcher="bestbuy_api", options=opts)


def test_sku_list_uses_in_operator():
    assert _selector(_t(skus=[43900, 2088495])) == "products(sku in(43900,2088495))"


def test_sku_list_wins_over_search():
    s = _selector(_t(skus=[1], search="ignored"))
    assert s == "products(sku in(1))"


def test_search_is_url_encoded():
    assert _selector(_t(search="pokemon elite trainer")) == \
        "products(search=pokemon%20elite%20trainer)"


def test_defaults_to_target_name():
    assert _selector(_t()) == "products(search=bb)"
