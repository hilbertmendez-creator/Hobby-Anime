import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.manual_review import ApprovalError, approve_rejection, list_rejections
from hobby_anime.models import TorrentDownload


class FakeGateway:
    def __init__(self) -> None:
        self.accepted: list[tuple[str, str, str, bool]] = []

    def accept(
        self,
        torrent_hash: str,
        verified_path: str,
        verified_category: str,
        resume: bool = False,
    ) -> TorrentDownload:
        self.accepted.append((torrent_hash, verified_path, verified_category, resume))
        return TorrentDownload(
            torrent_hash,
            "Rejected show",
            Path(verified_path) / "bad.mkv",
        )


class FailingGateway:
    def accept(self, *args: object, **kwargs: object) -> TorrentDownload:
        raise RuntimeError("qBittorrent unreachable")


def _seed_rejected(database: TrackingDatabase, tmp_path: Path) -> None:
    database.initialize()
    database.record_verification(
        TorrentDownload("hash-bad", "Rejected show", tmp_path / "bad.mkv"),
        "rejected",
        reason="No Spanish tracks",
    )


def test_list_rejections_returns_only_rejected(settings: Settings, tmp_path: Path) -> None:
    database = TrackingDatabase(settings.database_path)
    _seed_rejected(database, tmp_path)
    database.record_verification(
        TorrentDownload("hash-ok", "Verified", tmp_path / "ok.mkv"),
        "verified",
        reason="Spanish subtitles verified",
    )

    result = list_rejections(settings, database=database)

    assert [r.torrent_hash for r in result] == ["hash-bad"]


def test_approve_promotes_resumes_and_records_audit(settings: Settings, tmp_path: Path) -> None:
    database = TrackingDatabase(settings.database_path)
    _seed_rejected(database, tmp_path)
    gateway = FakeGateway()

    result = approve_rejection(settings, "hash-bad", gateway=gateway, database=database)

    assert gateway.accepted == [
        ("hash-bad", settings.qbt_verified_path, settings.qbt_verified_category, True)
    ]
    assert database.verification_status("hash-bad") == "verified"
    assert database.rejected_downloads() == []
    assert result.name == "Rejected show"
    with sqlite3.connect(database.path) as connection:
        reason = connection.execute(
            "SELECT reason FROM download_verification WHERE torrent_hash = 'hash-bad'"
        ).fetchone()[0]
    assert reason == "Manually approved (was rejected: No Spanish tracks)"


def test_approve_unknown_hash_raises_without_touching_gateway(settings: Settings) -> None:
    database = TrackingDatabase(settings.database_path)
    database.initialize()
    gateway = FakeGateway()

    with pytest.raises(ApprovalError):
        approve_rejection(settings, "nope", gateway=gateway, database=database)

    assert gateway.accepted == []


def test_approve_gateway_failure_leaves_row_rejected(settings: Settings, tmp_path: Path) -> None:
    database = TrackingDatabase(settings.database_path)
    _seed_rejected(database, tmp_path)

    with pytest.raises(RuntimeError):
        approve_rejection(settings, "hash-bad", gateway=FailingGateway(), database=database)

    assert database.verification_status("hash-bad") == "rejected"


def test_approve_queues_sonarr_import_when_enabled(settings: Settings, tmp_path: Path) -> None:
    settings = replace(
        settings,
        sonarr_enabled=True,
        sonarr_import_after_verify=True,
        sonarr_api_key="key",
    )
    database = TrackingDatabase(settings.database_path)
    _seed_rejected(database, tmp_path)

    approve_rejection(settings, "hash-bad", gateway=FakeGateway(), database=database)

    assert [d.torrent_hash for d in database.pending_imports()] == ["hash-bad"]
