from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit

from hobby_anime.models import (
    FeedItem,
    MediaInspection,
    RejectedDownload,
    StoredToken,
    TorrentDownload,
)

SCHEMA_VERSION = 3

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
CREATE TABLE IF NOT EXISTS download_verification (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    torrent_hash TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    content_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('processing', 'verified', 'rejected', 'error')),
    audio_languages TEXT NOT NULL DEFAULT '[]',
    subtitle_languages TEXT NOT NULL DEFAULT '[]',
    reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_download_verification_status
    ON download_verification(status);
CREATE TABLE IF NOT EXISTS library_import (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    torrent_hash TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    content_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK(
        status IN ('pending', 'processing', 'queued', 'imported', 'error')
    ),
    command_id INTEGER,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_import_status
    ON library_import(status);
CREATE TABLE IF NOT EXISTS anilist_token (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    access_token TEXT NOT NULL,
    token_type TEXT NOT NULL,
    obtained_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE TABLE IF NOT EXISTS anilist_mapping (
    series_id TEXT PRIMARY KEY,
    override_media_id INTEGER,
    auto_media_id INTEGER,
    updated_at TEXT NOT NULL
);
"""


class TrackingDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        os.chmod(self.path, 0o600)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            verification_schema = connection.execute(
                """
                SELECT sql FROM sqlite_master
                WHERE type = 'table' AND name = 'download_verification'
                """
            ).fetchone()
            needs_verification_migration = bool(
                verification_schema
                and "processing" not in str(verification_schema["sql"])
            )
            if needs_verification_migration:
                connection.execute(
                    "ALTER TABLE download_verification RENAME TO download_verification_v1"
                )
                connection.execute(
                    "DROP INDEX IF EXISTS idx_download_verification_status"
                )
            connection.executescript(SCHEMA)
            if needs_verification_migration:
                connection.execute(
                    """
                    INSERT INTO download_verification (
                        id, torrent_hash, name, content_path, status,
                        audio_languages, subtitle_languages, reason,
                        created_at, updated_at
                    )
                    SELECT
                        id, torrent_hash, name, content_path, status,
                        audio_languages, subtitle_languages, reason,
                        created_at, updated_at
                    FROM download_verification_v1
                    """
                )
                connection.execute("DROP TABLE download_verification_v1")
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

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

    def verification_status(self, torrent_hash: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT status FROM download_verification WHERE torrent_hash = ?",
                (torrent_hash,),
            ).fetchone()
        return str(row["status"]) if row else None

    def rejected_downloads(
        self,
        torrent_hash: str | None = None,
    ) -> list[RejectedDownload]:
        query = (
            "SELECT torrent_hash, name, reason, content_path, updated_at "
            "FROM download_verification WHERE status = 'rejected'"
        )
        params: tuple[str, ...] = ()
        if torrent_hash is not None:
            query += " AND torrent_hash = ?"
            params = (torrent_hash,)
        query += " ORDER BY updated_at DESC"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            RejectedDownload(
                torrent_hash=str(row["torrent_hash"]),
                name=str(row["name"]),
                reason=str(row["reason"] or ""),
                content_path=Path(str(row["content_path"])),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    def claim_verification(
        self,
        download: TorrentDownload,
        stale_after_minutes: int = 30,
    ) -> bool:
        now = datetime.now(UTC)
        stale_before = (now - timedelta(minutes=stale_after_minutes)).isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO download_verification (
                    torrent_hash, name, content_path, status, audio_languages,
                    subtitle_languages, reason, created_at, updated_at
                ) VALUES (?, ?, ?, 'processing', '[]', '[]', ?, ?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET
                    name = excluded.name,
                    content_path = excluded.content_path,
                    status = 'processing',
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                WHERE download_verification.status = 'error'
                   OR (
                       download_verification.status = 'processing'
                       AND download_verification.updated_at < ?
                   )
                """,
                (
                    download.torrent_hash,
                    download.name,
                    str(download.content_path),
                    "Verification in progress",
                    now.isoformat(),
                    now.isoformat(),
                    stale_before,
                ),
            )
        return cursor.rowcount == 1

    def record_verification(
        self,
        download: TorrentDownload,
        status: str,
        inspection: MediaInspection | None = None,
        reason: str = "",
    ) -> None:
        if status not in {"verified", "rejected", "error"}:
            raise ValueError(f"Invalid verification status: {status}")
        now = datetime.now(UTC).isoformat()
        audio_languages = inspection.audio_languages if inspection else ()
        subtitle_languages = inspection.subtitle_languages if inspection else ()
        final_reason = reason or (inspection.reason if inspection else "")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO download_verification (
                    torrent_hash, name, content_path, status, audio_languages,
                    subtitle_languages, reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET
                    name = excluded.name,
                    content_path = excluded.content_path,
                    status = excluded.status,
                    audio_languages = excluded.audio_languages,
                    subtitle_languages = excluded.subtitle_languages,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (
                    download.torrent_hash,
                    download.name,
                    str(download.content_path),
                    status,
                    json.dumps(audio_languages, ensure_ascii=False),
                    json.dumps(subtitle_languages, ensure_ascii=False),
                    final_reason[:2_000],
                    now,
                    now,
                ),
            )

    def queue_import(self, download: TorrentDownload) -> None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO library_import (
                    torrent_hash, name, content_path, status, command_id,
                    error_message, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', NULL, NULL, ?, ?)
                ON CONFLICT(torrent_hash) DO UPDATE SET
                    name = excluded.name,
                    content_path = excluded.content_path,
                    updated_at = excluded.updated_at
                WHERE library_import.status != 'imported'
                """,
                (
                    download.torrent_hash,
                    download.name,
                    str(download.content_path),
                    now,
                    now,
                ),
            )

    def pending_imports(self) -> list[TorrentDownload]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT torrent_hash, name, content_path
                FROM library_import
                WHERE status IN ('pending', 'error', 'processing', 'queued')
                ORDER BY updated_at
                """
            ).fetchall()
        return [
            TorrentDownload(
                torrent_hash=str(row["torrent_hash"]),
                name=str(row["name"]),
                content_path=Path(str(row["content_path"])),
            )
            for row in rows
        ]

    def claim_import(
        self,
        download: TorrentDownload,
        stale_after_minutes: int = 30,
    ) -> bool:
        now = datetime.now(UTC)
        stale_before = (now - timedelta(minutes=stale_after_minutes)).isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE library_import
                SET status = 'processing', error_message = NULL, updated_at = ?
                WHERE torrent_hash = ?
                  AND (
                      status IN ('pending', 'error', 'queued')
                      OR (status = 'processing' AND updated_at < ?)
                  )
                """,
                (now.isoformat(), download.torrent_hash, stale_before),
            )
        return cursor.rowcount == 1

    def record_import(
        self,
        torrent_hash: str,
        status: str,
        command_id: int | None = None,
        error_message: str = "",
    ) -> None:
        if status not in {"queued", "imported", "error"}:
            raise ValueError(f"Invalid import status: {status}")
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE library_import
                SET status = ?, command_id = ?, error_message = ?, updated_at = ?
                WHERE torrent_hash = ?
                """,
                (
                    status,
                    command_id,
                    error_message[:2_000] or None,
                    datetime.now(UTC).isoformat(),
                    torrent_hash,
                ),
            )

    def import_command_id(self, torrent_hash: str) -> int | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT command_id FROM library_import WHERE torrent_hash = ?",
                (torrent_hash,),
            ).fetchone()
        if not row or row["command_id"] is None:
            return None
        return int(row["command_id"])

    def import_status(self, torrent_hash: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT status FROM library_import WHERE torrent_hash = ?",
                (torrent_hash,),
            ).fetchone()
        return str(row["status"]) if row else None

    def pipeline_summary(self) -> dict[str, dict[str, int]]:
        tables = {
            "rss": "media_tracking",
            "verification": "download_verification",
            "import": "library_import",
        }
        summary: dict[str, dict[str, int]] = {}
        with self.connect() as connection:
            for name, table in tables.items():
                rows = connection.execute(
                    f"SELECT status, COUNT(*) AS total FROM {table} GROUP BY status"
                ).fetchall()
                summary[name] = {
                    str(row["status"]): int(row["total"])
                    for row in rows
                }
        return summary

    def save_token(self, token: StoredToken) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO anilist_token (
                    id, access_token, token_type, obtained_at, expires_at
                ) VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    access_token = excluded.access_token,
                    token_type = excluded.token_type,
                    obtained_at = excluded.obtained_at,
                    expires_at = excluded.expires_at
                """,
                (token.access_token, token.token_type, token.obtained_at, token.expires_at),
            )

    def get_token(self) -> StoredToken | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT access_token, token_type, obtained_at, expires_at "
                "FROM anilist_token WHERE id = 1"
            ).fetchone()
        if not row:
            return None
        return StoredToken(
            access_token=str(row["access_token"]),
            token_type=str(row["token_type"]),
            obtained_at=str(row["obtained_at"]),
            expires_at=str(row["expires_at"]) if row["expires_at"] is not None else None,
        )

    def get_mapping(self, series_id: str) -> dict[str, int | None] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT override_media_id, auto_media_id "
                "FROM anilist_mapping WHERE series_id = ?",
                (series_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "override_media_id": (
                int(row["override_media_id"])
                if row["override_media_id"] is not None
                else None
            ),
            "auto_media_id": (
                int(row["auto_media_id"]) if row["auto_media_id"] is not None else None
            ),
        }

    def upsert_mapping(self, series_id: str, media_id: int) -> None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO anilist_mapping (series_id, auto_media_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(series_id) DO UPDATE SET
                    auto_media_id = excluded.auto_media_id,
                    updated_at = excluded.updated_at
                """,
                (series_id, media_id, now),
            )

    def set_override(self, series_id: str, media_id: int) -> None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO anilist_mapping (series_id, override_media_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(series_id) DO UPDATE SET
                    override_media_id = excluded.override_media_id,
                    updated_at = excluded.updated_at
                """,
                (series_id, media_id, now),
            )

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
                    _safe_download_reference(item.download_url),
                    published_at,
                    status,
                    error_message,
                    now,
                    now,
                ),
            )


def _safe_download_reference(download_url: str) -> str:
    if download_url.startswith("magnet:"):
        return "magnet:[redacted]"
    parsed = urlsplit(download_url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
