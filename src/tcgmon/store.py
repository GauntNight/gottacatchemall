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
        # Append-only history of every state TRANSITION (not every poll): a
        # first sighting, an OOS->in_stock "hit", an in_stock->OOS sell-out,
        # etc. `alerted` flags the ones that fired a push. This is the dataset
        # for later pattern mining (when do drops land, how long stock lasts).
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT NOT NULL,
                key        TEXT NOT NULL,
                source     TEXT NOT NULL,
                old_status TEXT,
                new_status TEXT NOT NULL,
                title      TEXT,
                url        TEXT,
                price      TEXT,
                alerted    INTEGER NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_signals_key_ts ON signals (key, ts)"
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
        alerted = is_alertable(old, obs.status)

        # Record the transition (first sighting, or a genuine old->new change)
        # to the append-only signals log. Steady state (old == new) is skipped
        # so the log stays a history of *changes*, not of every poll.
        if old is None or old is not obs.status:
            self._conn.execute(
                """
                INSERT INTO signals
                    (ts, key, source, old_status, new_status, title, url, price, alerted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now, obs.key, source, old.value if old else None,
                 obs.status.value, obs.title, obs.url, obs.price, int(alerted)),
            )
        self._conn.commit()

        if alerted:
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

    def recent_signals(self, limit: int = 50) -> list[dict]:
        """Most-recent transitions first — for inspection / pattern analysis."""
        rows = self._conn.execute(
            "SELECT ts, key, source, old_status, new_status, title, url, price, "
            "alerted FROM signals ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
