"""Core data types shared across fetchers, store, and notifier."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    """Three-valued stock state plus a ``listed`` signal for Tier 1 news.

    Design rule #2: bot challenges, timeouts, and parse failures are
    ``UNKNOWN`` — we never alert on them and never overwrite a known
    state with ``UNKNOWN``.
    """

    UNKNOWN = "unknown"
    OUT_OF_STOCK = "out_of_stock"
    IN_STOCK = "in_stock"
    # A Tier 1 aggregate item (news post / new listing) exists. Used to
    # fire a one-time "something appeared" alert the first time a key is
    # seen, without claiming the item is buyable.
    LISTED = "listed"


@dataclass(slots=True)
class Observation:
    """A single thing a fetcher saw this cycle.

    ``key`` is the stable identity used for edge detection — e.g.
    ``reddit:r/PKMNTCGDeals:t3_abc`` for a post, or ``bestbuy:6418599``
    for a SKU. The store compares the new ``status`` against the last
    stored status for this key and decides whether to alert.
    """

    key: str
    status: Status
    title: str | None = None
    url: str | None = None
    price: str | None = None


@dataclass(slots=True)
class Alert:
    """An edge transition worth notifying about."""

    key: str
    old_status: Status | None
    new_status: Status
    title: str | None
    url: str | None
    price: str | None
    source: str
