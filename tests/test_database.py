import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hobby_anime.database import TrackingDatabase
from hobby_anime.models import FeedItem, TorrentDownload


def test_tracking_database_retries_errors_and_skips_added(tmp_path: Path) -> None:
    database = TrackingDatabase(tmp_path / "nested" / "tracking.db")
    item = FeedItem(
        "fingerprint",
        "Example",
        "https://tracker.example/download/file.torrent?passkey=secret",
    )
    database.initialize()

    database.record_error(item, "temporary failure")
    assert database.was_added(item.fingerprint) is False

    database.record_added(item)
    assert database.was_added(item.fingerprint) is True
    assert database.pipeline_summary()["rss"] == {"added": 1}
    if sys.platform != "win32":
        # os.chmod only toggles the read-only flag on Windows, it can't
        # express POSIX permission bits — the 0600 guarantee only applies
        # on the POSIX hosts (the Docker/NAS deployment target) this runs on.
        assert database.path.stat().st_mode & 0o777 == 0o600

    with sqlite3.connect(database.path) as connection:
        stored_url = connection.execute(
            "SELECT download_url FROM media_tracking"
        ).fetchone()[0]
    assert stored_url == "https://tracker.example/download/file.torrent"


def test_initialize_migrates_legacy_verification_schema(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE download_verification (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                torrent_hash TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                content_path TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('verified', 'rejected', 'error')),
                audio_languages TEXT NOT NULL DEFAULT '[]',
                subtitle_languages TEXT NOT NULL DEFAULT '[]',
                reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    database = TrackingDatabase(path)
    database.initialize()

    with sqlite3.connect(path) as connection:
        schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'download_verification'"
        ).fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert "processing" in schema
    assert version == 2


def test_claim_verification_honors_explicit_stale_window(tmp_path: Path) -> None:
    database = TrackingDatabase(tmp_path / "tracking.db")
    database.initialize()
    download = TorrentDownload("hash", "Example", tmp_path / "example.mkv")
    assert database.claim_verification(download, stale_after_minutes=30) is True

    stale_at = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "UPDATE download_verification SET updated_at = ? WHERE torrent_hash = ?",
            (stale_at, "hash"),
        )

    assert database.claim_verification(download, stale_after_minutes=30) is False
    assert database.claim_verification(download, stale_after_minutes=10) is True


def test_claim_import_honors_explicit_stale_window(tmp_path: Path) -> None:
    database = TrackingDatabase(tmp_path / "tracking.db")
    database.initialize()
    download = TorrentDownload("hash", "Example", tmp_path / "example.mkv")
    database.queue_import(download)
    assert database.claim_import(download, stale_after_minutes=30) is True

    stale_at = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "UPDATE library_import SET updated_at = ? WHERE torrent_hash = ?",
            (stale_at, "hash"),
        )

    assert database.claim_import(download, stale_after_minutes=30) is False
    assert database.claim_import(download, stale_after_minutes=10) is True
