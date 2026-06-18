"""Target local-sweep store selection: state filtering + cap."""

from __future__ import annotations

from tcgmon.fetchers.target_nearby import select_stores, _to_abbrev


def test_to_abbrev_converts_full_name():
    # redsky's fulfillment endpoint 400s on a full state name; needs "NJ".
    assert _to_abbrev("New Jersey") == "NJ"
    assert _to_abbrev("new york") == "NY"


def test_to_abbrev_passes_through_two_letter():
    assert _to_abbrev("NJ") == "NJ"
    assert _to_abbrev("nj") == "NJ"


def test_to_abbrev_handles_none_and_unknown():
    assert _to_abbrev(None) == ""
    assert _to_abbrev("Guam") == "Guam"


def _raw(sid, city, state, lat="40.0", lon="-74.0"):
    return {"store_id": sid, "mailing_address": {"city": city, "state": state},
            "geographic_specifications": {"latitude": lat, "longitude": lon}}


STORES = [
    _raw(1263, "Edgewater", "New Jersey"),
    _raw(3337, "New York", "New York"),
    _raw(2103, "North Bergen", "New Jersey"),
    _raw(3394, "New York City", "New York"),
    _raw(2475, "Jersey City", "New Jersey"),
]


def test_nj_only_filter_skips_ny():
    out = select_stores(STORES, ["NJ"], limit=12)
    assert [s["store_id"] for s in out] == ["1263", "2103", "2475"]
    assert all(s["state"] == "New Jersey" for s in out)


def test_full_state_name_also_matches():
    assert len(select_stores(STORES, ["New Jersey"], limit=12)) == 3


def test_limit_caps_after_filtering():
    out = select_stores(STORES, ["NJ"], limit=2)
    assert [s["store_id"] for s in out] == ["1263", "2103"]


def test_no_filter_returns_all_up_to_limit():
    assert len(select_stores(STORES, None, limit=12)) == 5


def test_carries_geo_and_city():
    s = select_stores(STORES, ["NJ"], limit=1)[0]
    assert s["city"] == "Edgewater"
    assert s["latitude"] == "40.0" and s["longitude"] == "-74.0"


def test_skips_records_without_store_id():
    raw = [{"mailing_address": {"city": "X", "state": "New Jersey"}}, _raw(99, "Y", "New Jersey")]
    out = select_stores(raw, ["NJ"], limit=12)
    assert [s["store_id"] for s in out] == ["99"]
