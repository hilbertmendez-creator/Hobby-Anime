from dataclasses import replace
from pathlib import Path

from hobby_anime.config import Settings
from hobby_anime.doctor import run_checks


class FakeResponse:
    text = "Healthy"

    def raise_for_status(self) -> None:
        return None


class FakeSonarr:
    def __init__(self, *args: object) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {"version": "4.0"}

    def download_client_config(self) -> dict[str, object]:
        return {"enableCompletedDownloadHandling": False}

    def root_folders(self) -> list[dict[str, object]]:
        return [{"path": "/data/media/anime"}]


class FakeProwlarr:
    def __init__(self, *args: object) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {"version": "2.0"}

    def applications(self) -> list[dict[str, object]]:
        return [{"name": "Sonarr", "implementation": "Sonarr"}]


class FakeBazarr:
    def __init__(self, *args: object) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {"version": "1.5"}


def test_doctor_validates_hybrid_import_policy(
    settings: Settings,
    tmp_path: Path,
    monkeypatch,
) -> None:
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    configured = replace(
        settings,
        qbt_save_path=str(quarantine),
        sonarr_enabled=True,
        sonarr_api_key="secret",
        prowlarr_enabled=True,
        prowlarr_api_key="secret",
        bazarr_enabled=True,
        bazarr_api_key="secret",
    )
    monkeypatch.setattr(
        "hobby_anime.doctor.QBittorrentGateway.connect",
        lambda _: "2.14",
    )
    monkeypatch.setattr("hobby_anime.doctor.requests.get", lambda *a, **k: FakeResponse())
    monkeypatch.setattr("hobby_anime.doctor.SonarrClient", FakeSonarr)
    monkeypatch.setattr("hobby_anime.doctor.ProwlarrClient", FakeProwlarr)
    monkeypatch.setattr("hobby_anime.doctor.BazarrClient", FakeBazarr)

    checks = run_checks(configured)

    assert checks["sonarr_import_policy"]["ok"] is True
    assert checks["sonarr_media_root"]["ok"] is True
    assert checks["prowlarr_sonarr"]["ok"] is True
    assert checks["bazarr"]["ok"] is True
