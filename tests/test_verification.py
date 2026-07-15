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

    def completed(self, categories: tuple[str, ...]) -> list[TorrentDownload]:
        return self.downloads

    def accept(self, torrent_hash: str, path: str, category: str) -> TorrentDownload:
        self.accepted.append((torrent_hash, path, category))
        source = next(
            download for download in self.downloads if download.torrent_hash == torrent_hash
        )
        destination_root = Path(path)
        destination_root.mkdir(parents=True, exist_ok=True)
        destination = destination_root / source.content_path.name
        source.content_path.rename(destination)
        return TorrentDownload(torrent_hash, source.name, destination)

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


class FakeSonarr:
    def __init__(self) -> None:
        self.scanned_hashes: list[str] = []

    def scan_verified(
        self,
        content_path: Path,
        verified_root: Path,
        download_client_id: str,
    ) -> int:
        self.scanned_hashes.append(download_client_id)
        return 7

    def wait_for_command(
        self,
        command_id: int,
        timeout_seconds: int,
        poll_seconds: int,
    ) -> dict[str, object]:
        return {"status": "completed", "result": "successful"}


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

    repeated = run_verification(
        configured,
        gateway=gateway,
        inspector=FakeInspector(),
        database=database,
    )

    assert repeated.skipped == 2
    assert len(gateway.accepted) == 1
    assert len(gateway.rejected) == 1


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


def test_hybrid_flow_imports_only_verified_download(
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
        sonarr_enabled=True,
        sonarr_api_key="secret",
        sonarr_verified_root=verified,
        notify_on_verification=False,
        notify_on_import=False,
    )
    gateway = FakeGateway(
        [
            TorrentDownload("spanish-hash", "Spanish", spanish),
            TorrentDownload("english-hash", "English", english),
        ]
    )
    sonarr = FakeSonarr()

    result = run_verification(
        configured,
        gateway=gateway,
        inspector=FakeInspector(),
        database=TrackingDatabase(settings.database_path),
        sonarr_client=sonarr,
    )

    assert result.imported == 1
    assert result.import_failed == 0
    assert sonarr.scanned_hashes == ["spanish-hash"]
