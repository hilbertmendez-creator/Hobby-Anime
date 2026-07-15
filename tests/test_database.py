import sqlite3
from pathlib import Path

from hobby_anime.database import TrackingDatabase
from hobby_anime.models import FeedItem


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
