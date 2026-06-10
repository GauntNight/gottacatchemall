"""SQLite-backed state store with edge detection.

Design rule #1: store the last state per ``key`` and alert ONLY on a
transition (``OOS -> in_stock``, ``absent -> listed``, etc.), never on a
level. Design rule #2: ``UNKNOWN`` never alerts and never overwrites a
known state.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from pathlib import Path

from .models import Alert, Observation, Status


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# Which (old -> new) transitions are worth an alert. ``None`` means the
# key has never been seen before.
def is_alertable(old: Status | None, new: Status) -> bool:
    if new is Status.UNKNOWN:
        return False
    if old is None:
        # First sighting. A brand-new listing or an item that's already
        # buyable is news; an item we first meet as OOS is not.
        return new in (Status.LISTED, Status.IN_STOCK)
    if old is new:
        return False
    # Known-state transitions that mean "go buy it now".
    if new is Status.IN_STOCK and old in (Status.OUT_OF_STOCK, Status.LISTED):
        return True
    return False


class StateStore:
    """Persistent (source, key) -> status map with edge detection."""

    def __init__(self, path: str | Path = "state.db") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS state (
                key        TEXT PRIMARY KEY,
                source     TEXT NOT NULL,
                status     TEXT NOT NULL,
                title      TEXT,
                url        TEXT,
                price      TEXT,
                first_seen TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def get_status(self, key: str) -> Status | None:
        row = self._conn.execute(
            "SELECT status FROM state WHERE key = ?", (key,)
        ).fetchone()
        return Status(row["status"]) if row else None

    def record(self, source: str, obs: Observation) -> Alert | None:
        """Apply an observation; return an Alert iff it's an edge worth firing.

        ``UNKNOWN`` observations are dropped entirely: they neither create
        a row nor overwrite an existing known state.
        """
        old = self.get_status(obs.key)

        if obs.status is Status.UNKNOWN:
            return None

        now = _now()
        if old is None:
            self._conn.execute(
                """
                INSERT INTO state
                    (key, source, status, title, url, price, first_seen, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (obs.key, source, obs.status.value, obs.title, obs.url,
                 obs.price, now, now),
            )
        else:
            self._conn.execute(
                """
                UPDATE state
                   SET status = ?, title = ?, url = ?, price = ?, updated_at = ?
                 WHERE key = ?
                """,
                (obs.status.value, obs.title, obs.url, obs.price, now, obs.key),
            )
        self._conn.commit()

        if is_alertable(old, obs.status):
            return Alert(
                key=obs.key,
                old_status=old,
                new_status=obs.status,
                title=obs.title,
                url=obs.url,
                price=obs.price,
                source=source,
            )
        return None

    def close(self) -> None:
        self._conn.close()
