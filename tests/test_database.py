import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hobby_anime.database import TrackingDatabase
from hobby_anime.models import FeedItem, StoredToken, TorrentDownload


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
    assert version == 3


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


def test_rejected_downloads_lists_only_rejected(tmp_path: Path) -> None:
    database = TrackingDatabase(tmp_path / "tracking.db")
    database.initialize()
    database.record_verification(
        TorrentDownload("hash-ok", "Verified show", Path("/data/torrents/verified/ok.mkv")),
        "verified",
        reason="Spanish subtitles verified",
    )
    database.record_verification(
        TorrentDownload("hash-bad", "Rejected show", Path("/data/torrents/quarantine/bad.mkv")),
        "rejected",
        reason="No Spanish tracks",
    )

    downloads = database.rejected_downloads()

    assert [d.torrent_hash for d in downloads] == ["hash-bad"]
    assert downloads[0].name == "Rejected show"
    assert downloads[0].reason == "No Spanish tracks"
    assert downloads[0].content_path == Path("/data/torrents/quarantine/bad.mkv")


def test_rejected_downloads_filters_by_hash(tmp_path: Path) -> None:
    database = TrackingDatabase(tmp_path / "tracking.db")
    database.initialize()
    for index in range(2):
        database.record_verification(
            TorrentDownload(f"hash-{index}", f"Show {index}", Path(f"/q/{index}.mkv")),
            "rejected",
            reason=f"reason {index}",
        )

    downloads = database.rejected_downloads("hash-1")

    assert len(downloads) == 1
    assert downloads[0].torrent_hash == "hash-1"


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


def test_initialize_creates_anilist_tables_and_bumps_schema_version(
    tmp_path: Path,
) -> None:
    database = TrackingDatabase(tmp_path / "tracking.db")

    database.initialize()

    with sqlite3.connect(database.path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert version == 3
    assert "anilist_token" in tables
    assert "anilist_mapping" in tables
    if sys.platform != "win32":
        assert database.path.stat().st_mode & 0o777 == 0o600


def test_save_and_get_token_roundtrip(tmp_path: Path) -> None:
    database = TrackingDatabase(tmp_path / "tracking.db")
    database.initialize()
    assert database.get_token() is None

    token = StoredToken(
        access_token="secret-access-token",
        token_type="Bearer",
        obtained_at="2026-07-19T00:00:00+00:00",
        expires_at="2026-08-19T00:00:00+00:00",
    )
    database.save_token(token)

    stored = database.get_token()
    assert stored == token


def test_save_token_overwrites_previous_token(tmp_path: Path) -> None:
    database = TrackingDatabase(tmp_path / "tracking.db")
    database.initialize()
    database.save_token(
        StoredToken(
            access_token="first-token",
            token_type="Bearer",
            obtained_at="2026-07-19T00:00:00+00:00",
            expires_at=None,
        )
    )
    database.save_token(
        StoredToken(
            access_token="second-token",
            token_type="Bearer",
            obtained_at="2026-07-20T00:00:00+00:00",
            expires_at=None,
        )
    )

    stored = database.get_token()

    assert stored is not None
    assert stored.access_token == "second-token"
    with sqlite3.connect(database.path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM anilist_token").fetchone()[0]
    assert count == 1


def test_get_mapping_returns_none_when_absent(tmp_path: Path) -> None:
    database = TrackingDatabase(tmp_path / "tracking.db")
    database.initialize()

    assert database.get_mapping("series-1") is None


def test_upsert_mapping_stores_auto_match(tmp_path: Path) -> None:
    database = TrackingDatabase(tmp_path / "tracking.db")
    database.initialize()

    database.upsert_mapping("series-1", 101)

    mapping = database.get_mapping("series-1")
    assert mapping is not None
    assert mapping["auto_media_id"] == 101
    assert mapping["override_media_id"] is None


def test_set_override_wins_over_auto_match_in_get_mapping(tmp_path: Path) -> None:
    database = TrackingDatabase(tmp_path / "tracking.db")
    database.initialize()
    database.upsert_mapping("series-1", 101)

    database.set_override("series-1", 202)

    mapping = database.get_mapping("series-1")
    assert mapping is not None
    assert mapping["auto_media_id"] == 101
    assert mapping["override_media_id"] == 202


def test_upsert_mapping_does_not_clear_existing_override(tmp_path: Path) -> None:
    database = TrackingDatabase(tmp_path / "tracking.db")
    database.initialize()
    database.set_override("series-1", 202)

    database.upsert_mapping("series-1", 303)

    mapping = database.get_mapping("series-1")
    assert mapping is not None
    assert mapping["auto_media_id"] == 303
    assert mapping["override_media_id"] == 202
