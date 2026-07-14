from dataclasses import replace
from pathlib import Path

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.models import MediaInspection, TorrentDownload
from hobby_anime.verification import run_verification


class FakeGateway:
    def __init__(self, downloads: list[TorrentDownload]) -> None:
        self.downloads = downloads
        self.accepted: list[tuple[str, str, str]] = []
        self.rejected: list[tuple[str, str]] = []

    def completed(self) -> list[TorrentDownload]:
        return self.downloads

    def accept(self, torrent_hash: str, path: str, category: str) -> None:
        self.accepted.append((torrent_hash, path, category))

    def reject(self, torrent_hash: str, category: str) -> None:
        self.rejected.append((torrent_hash, category))


class FakeInspector:
    def inspect(self, content_path: Path) -> MediaInspection:
        if "spanish" in content_path.name:
            return MediaInspection(
                accepted=True,
                subtitle_languages=("spa",),
                inspected_files=(content_path,),
                reason="Spanish subtitles verified",
            )
        return MediaInspection(
            accepted=False,
            subtitle_languages=("eng",),
            inspected_files=(content_path,),
            reason="No Spanish tracks",
        )


def test_verification_accepts_and_rejects_completed_downloads(
    settings: Settings,
    tmp_path: Path,
) -> None:
    quarantine = tmp_path / "torrents" / "quarantine"
    verified = tmp_path / "torrents" / "verified"
    quarantine.mkdir(parents=True)
    spanish = quarantine / "spanish.mkv"
    english = quarantine / "english.mkv"
    spanish.touch()
    english.touch()
    configured = replace(
        settings,
        qbt_save_path=str(quarantine),
        qbt_verified_path=str(verified),
    )
    downloads = [
        TorrentDownload("spanish-hash", "Spanish episode", spanish),
        TorrentDownload("english-hash", "English episode", english),
    ]
    gateway = FakeGateway(downloads)
    database = TrackingDatabase(settings.database_path)

    result = run_verification(
        configured,
        gateway=gateway,
        inspector=FakeInspector(),
        database=database,
    )

    assert result.verified == 1
    assert result.rejected == 1
    assert gateway.accepted[0][0] == "spanish-hash"
    assert gateway.rejected[0][0] == "english-hash"
    assert database.verification_status("spanish-hash") == "verified"
    assert database.verification_status("english-hash") == "rejected"


def test_verification_fails_closed_outside_quarantine(
    settings: Settings,
    tmp_path: Path,
) -> None:
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    outside = tmp_path / "outside.mkv"
    outside.touch()
    configured = replace(settings, qbt_save_path=str(quarantine))
    gateway = FakeGateway([TorrentDownload("hash", "Outside", outside)])
    database = TrackingDatabase(settings.database_path)

    result = run_verification(
        configured,
        gateway=gateway,
        inspector=FakeInspector(),
        database=database,
    )

    assert result.failed == 1
    assert gateway.accepted == []
    assert gateway.rejected == []
    assert database.verification_status("hash") == "error"
