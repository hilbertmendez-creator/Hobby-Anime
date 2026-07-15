from pathlib import Path

import pytest

from hobby_anime.sonarr_client import SonarrClient


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(("GET", url, kwargs))
        return FakeResponse(self.responses.pop(0))

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(("POST", url, kwargs))
        return FakeResponse(self.responses.pop(0))


def test_scan_verified_queues_copy_import(tmp_path: Path) -> None:
    verified = tmp_path / "verified"
    verified.mkdir()
    episode = verified / "episode.mkv"
    episode.touch()
    session = FakeSession([{"id": 42}])
    client = SonarrClient("http://sonarr:8989", "secret", session=session)

    command_id = client.scan_verified(episode, verified, "torrent-hash")

    assert command_id == 42
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url.endswith("/api/v3/command")
    assert kwargs["headers"]["X-Api-Key"] == "secret"
    assert kwargs["json"] == {
        "name": "DownloadedEpisodesScan",
        "path": str(episode),
        "downloadClientId": "torrent-hash",
        "importMode": "copy",
    }


def test_scan_verified_rejects_path_outside_root(tmp_path: Path) -> None:
    verified = tmp_path / "verified"
    verified.mkdir()
    outside = tmp_path / "outside.mkv"
    outside.touch()
    client = SonarrClient(
        "http://sonarr:8989",
        "secret",
        session=FakeSession([]),
    )

    with pytest.raises(ValueError, match="outside verified storage"):
        client.scan_verified(outside, verified, "hash")


def test_wait_for_command_reports_success_and_failure() -> None:
    success_session = FakeSession(
        [
            {"id": 1, "status": "queued"},
            {"id": 1, "status": "completed", "result": "successful"},
        ]
    )
    success = SonarrClient(
        "http://sonarr:8989",
        "secret",
        session=success_session,
        sleeper=lambda _: None,
    )

    assert success.wait_for_command(1, 10, 1)["status"] == "completed"

    failed = SonarrClient(
        "http://sonarr:8989",
        "secret",
        session=FakeSession(
            [{"id": 2, "status": "completed", "result": "unsuccessful"}]
        ),
    )
    with pytest.raises(RuntimeError, match="unsuccessful"):
        failed.wait_for_command(2, 10, 1)
