"""Edge-detection tests — the heart of the monitor (design rules #1, #2).

These are pure logic + a temp SQLite file; no network needed.
"""

from __future__ import annotations

from tcgmon.models import Observation, Status
from tcgmon.store import StateStore, is_alertable


# ── is_alertable: the transition table ────────────────────────────────────

def test_oos_to_in_stock_alerts():
    assert is_alertable(Status.OUT_OF_STOCK, Status.IN_STOCK) is True


def test_listed_to_in_stock_alerts():
    assert is_alertable(Status.LISTED, Status.IN_STOCK) is True


def test_first_sighting_in_stock_alerts():
    assert is_alertable(None, Status.IN_STOCK) is True


def test_first_sighting_listed_alerts():
    # Tier 1: a new matching post fires exactly one alert.
    assert is_alertable(None, Status.LISTED) is True


def test_first_sighting_oos_is_quiet():
    assert is_alertable(None, Status.OUT_OF_STOCK) is False


def test_unknown_never_alerts():
    for old in (None, Status.IN_STOCK, Status.OUT_OF_STOCK, Status.LISTED):
        assert is_alertable(old, Status.UNKNOWN) is False


def test_in_stock_to_oos_is_quiet():
    assert is_alertable(Status.IN_STOCK, Status.OUT_OF_STOCK) is False


def test_no_change_is_quiet():
    assert is_alertable(Status.IN_STOCK, Status.IN_STOCK) is False


# ── StateStore behavior ───────────────────────────────────────────────────

def _store(tmp_path):
    return StateStore(tmp_path / "t.db")


def test_record_first_in_stock_returns_alert(tmp_path):
    s = _store(tmp_path)
    obs = Observation(key="bestbuy:1", status=Status.IN_STOCK, title="ETB")
    assert s.record("bestbuy", obs) is not None
    s.close()


def test_record_is_idempotent_on_steady_state(tmp_path):
    s = _store(tmp_path)
    obs = Observation(key="bestbuy:1", status=Status.IN_STOCK, title="ETB")
    assert s.record("bestbuy", obs) is not None   # first sighting alerts
    assert s.record("bestbuy", obs) is None        # same state, no re-alert
    s.close()


def test_restock_edge_fires(tmp_path):
    s = _store(tmp_path)
    key = "shopify:galactic"
    assert s.record("galactic", Observation(key=key, status=Status.OUT_OF_STOCK)) is None
    alert = s.record("galactic", Observation(key=key, status=Status.IN_STOCK))
    assert alert is not None
    assert alert.old_status is Status.OUT_OF_STOCK
    assert alert.new_status is Status.IN_STOCK
    s.close()


def test_unknown_does_not_overwrite_known(tmp_path):
    s = _store(tmp_path)
    key = "walmart:etb"
    s.record("walmart", Observation(key=key, status=Status.IN_STOCK))
    # A challenge/timeout arrives as UNKNOWN; it must not clobber IN_STOCK.
    s.record("walmart", Observation(key=key, status=Status.UNKNOWN))
    assert s.get_status(key) is Status.IN_STOCK
    s.close()


def test_unknown_first_sighting_is_not_stored(tmp_path):
    s = _store(tmp_path)
    s.record("walmart", Observation(key="w:1", status=Status.UNKNOWN))
    assert s.get_status("w:1") is None
    s.close()
