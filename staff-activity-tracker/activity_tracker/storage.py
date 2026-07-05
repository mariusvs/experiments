"""Local SQLite storage for activity samples.

The schema is intentionally coarse: we keep one row per sample interval per
foreground window, plus aggregate input counts. No raw keystroke content is ever
stored (there is no column for it).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,      -- ISO8601 UTC, start of sample
    duration      REAL    NOT NULL,      -- seconds this sample covers
    user          TEXT    NOT NULL,
    host          TEXT    NOT NULL,
    device_label  TEXT,
    app           TEXT,                  -- process / application name
    window_title  TEXT,                  -- foreground window title
    url           TEXT,                  -- browser URL/host when available
    idle          INTEGER NOT NULL DEFAULT 0,  -- 1 if user idle during sample
    key_count     INTEGER NOT NULL DEFAULT 0,  -- keystrokes counted (NOT content)
    mouse_count   INTEGER NOT NULL DEFAULT 0,  -- mouse events counted
    mouse_dist    REAL    NOT NULL DEFAULT 0,  -- cursor travel in pixels
    uploaded      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts);
CREATE INDEX IF NOT EXISTS idx_samples_uploaded ON samples(uploaded);
"""


class Storage:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def insert_sample(self, **fields) -> int:
        cols = (
            "ts", "duration", "user", "host", "device_label", "app",
            "window_title", "url", "idle", "key_count", "mouse_count",
            "mouse_dist",
        )
        values = [fields.get(c) for c in cols]
        placeholders = ", ".join("?" for _ in cols)
        cur = self._conn.execute(
            f"INSERT INTO samples ({', '.join(cols)}) VALUES ({placeholders})",
            values,
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def unuploaded(self, limit: int = 500) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM samples WHERE uploaded = 0 ORDER BY id LIMIT ?", (limit,)
        )
        return cur.fetchall()

    def mark_uploaded(self, ids: list[int]) -> None:
        if not ids:
            return
        self._conn.executemany(
            "UPDATE samples SET uploaded = 1 WHERE id = ?", [(i,) for i in ids]
        )
        self._conn.commit()

    def query(
        self,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM samples WHERE 1=1"
        params: list = []
        if since:
            sql += " AND ts >= ?"
            params.append(since)
        if until:
            sql += " AND ts <= ?"
            params.append(until)
        sql += " ORDER BY ts"
        return self._conn.execute(sql, params).fetchall()

    def purge_older_than(self, cutoff_iso: str) -> int:
        """Delete samples with ts strictly older than cutoff_iso. Returns count."""
        cur = self._conn.execute("DELETE FROM samples WHERE ts < ?", (cutoff_iso,))
        self._conn.commit()
        return cur.rowcount

    def distinct_users(self, since: Optional[str] = None) -> list[str]:
        sql = "SELECT DISTINCT user FROM samples"
        params: list = []
        if since:
            sql += " WHERE ts >= ?"
            params.append(since)
        sql += " ORDER BY user"
        return [r["user"] for r in self._conn.execute(sql, params).fetchall()]

    def oldest_ts(self) -> Optional[str]:
        row = self._conn.execute("SELECT MIN(ts) AS m FROM samples").fetchone()
        return row["m"] if row and row["m"] else None

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def batch(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
