"""Target keyword filter tests — ``keywords`` (OR) and ``require`` (AND).

Pure logic, no network or filesystem. Guards the "only find the preorder
we're looking for" behaviour: a buyable signal AND the set name.
"""

from __future__ import annotations

from tcgmon.config import Target


def _t(**kw) -> Target:
    return Target(name="t", fetcher="rss", **kw)


def test_no_filters_matches_everything():
    assert _t().matches("anything at all") is True


def test_keywords_are_or_and_case_insensitive():
    t = _t(keywords=["preorder", "restock"])
    assert t.matches("Restock LIVE now") is True   # matches one of several
    assert t.matches("just a deck help thread") is False


def test_require_is_and():
    t = _t(require=["pitch black", "preorder"])
    assert t.matches("Pitch Black preorder is live") is True
    assert t.matches("Pitch Black promos revealed") is False  # missing 'preorder'


def test_keywords_and_require_combine():
    # (any purchase signal) AND (the set name) — the pokebeach-news config.
    t = _t(keywords=["preorder", "now live", "in stock"], require=["pitch black"])
    assert t.matches('"Pitch Black" Preorders Now Live on Pokemon Center!') is True
    # Right set, but a reveal — no purchase signal -> filtered out.
    assert t.matches('First "Pitch Black" English Cards Revealed!') is False
    # Purchase signal, wrong set -> filtered out.
    assert t.matches("Chaos Rising restock now live") is False
