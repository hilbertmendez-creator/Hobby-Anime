from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from hobby_anime.models import FeedItem


SCHEMA = """
CREATE TABLE IF NOT EXISTS media_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    download_url TEXT NOT NULL,
    published_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('added', 'error')),
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_media_tracking_status
    ON media_tracking(status);
"""


class TrackingDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def was_added(self, fingerprint: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM media_tracking WHERE fingerprint = ? AND status = 'added'",
                (fingerprint,),
            ).fetchone()
        return row is not None

    def record_added(self, item: FeedItem) -> None:
        self._upsert(item, "added", None)

    def record_error(self, item: FeedItem, message: str) -> None:
        self._upsert(item, "error", message[:2_000])

    def _upsert(self, item: FeedItem, status: str, error_message: str | None) -> None:
        now = datetime.now(UTC).isoformat()
        published_at = item.published_at.isoformat() if item.published_at else None
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO media_tracking (
                    fingerprint, title, download_url, published_at, status,
                    error_message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    title = excluded.title,
                    download_url = excluded.download_url,
                    published_at = excluded.published_at,
                    status = excluded.status,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
                """,
                (
                    item.fingerprint,
                    item.title,
                    item.download_url,
                    published_at,
                    status,
                    error_message,
                    now,
                    now,
                ),
            )
