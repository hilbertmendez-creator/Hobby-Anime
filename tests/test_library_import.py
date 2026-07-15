from dataclasses import replace
from pathlib import Path

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.library_import import run_pending_imports
from hobby_anime.models import TorrentDownload


class FakeSonarr:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.scans: list[tuple[Path, Path, str]] = []

    def scan_verified(
        self,
        content_path: Path,
        verified_root: Path,
        download_client_id: str,
    ) -> int:
        self.scans.append((content_path, verified_root, download_client_id))
        if self.fail:
            raise RuntimeError("Sonarr unavailable")
        return 42

    def wait_for_command(
        self,
        command_id: int,
        timeout_seconds: int,
        poll_seconds: int,
    ) -> dict[str, object]:
        return {"id": command_id, "status": "completed", "result": "successful"}


def test_imports_verified_download_once(settings: Settings, tmp_path: Path) -> None:
    verified = tmp_path / "verified"
    verified.mkdir()
    episode = verified / "episode.mkv"
    episode.touch()
    configured = replace(
        settings,
        sonarr_enabled=True,
        sonarr_api_key="secret",
        sonarr_verified_root=verified,
        notify_on_import=False,
    )
    database = TrackingDatabase(settings.database_path)
    database.initialize()
    database.queue_import(TorrentDownload("hash", "Episode", episode))
    sonarr = FakeSonarr()

    first = run_pending_imports(configured, client=sonarr, database=database)
    second = run_pending_imports(configured, client=sonarr, database=database)

    assert first.imported == 1
    assert second.discovered == 0
    assert len(sonarr.scans) == 1
    assert database.import_status("hash") == "imported"


def test_failed_import_remains_retryable(settings: Settings, tmp_path: Path) -> None:
    verified = tmp_path / "verified"
    verified.mkdir()
    episode = verified / "episode.mkv"
    episode.touch()
    configured = replace(
        settings,
        sonarr_enabled=True,
        sonarr_api_key="secret",
        sonarr_verified_root=verified,
        notify_on_import=False,
    )
    database = TrackingDatabase(settings.database_path)
    database.initialize()
    database.queue_import(TorrentDownload("hash", "Episode", episode))

    failed = run_pending_imports(
        configured,
        client=FakeSonarr(fail=True),
        database=database,
    )
    retried = run_pending_imports(
        configured,
        client=FakeSonarr(),
        database=database,
    )

    assert failed.failed == 1
    assert database.import_status("hash") == "imported"
    assert retried.imported == 1
