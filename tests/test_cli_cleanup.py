import json
import sys
from dataclasses import replace

import pytest

import hobby_anime.cli as cli
from hobby_anime.config import Settings
from hobby_anime.models import WatchedSeries


def _jellyfin_settings(settings: Settings) -> Settings:
    return replace(
        settings,
        jellyfin_api_key="top-secret-key",
        jellyfin_user_id="user-1",
        sonarr_media_root=settings.media_path,
    )


def _fake_client_factory(series_dir):
    return lambda *args, **kwargs: type(
        "FakeClient",
        (),
        {
            "list_watched_series": lambda self: [
                WatchedSeries(id="s1", name="Frieren", total_episodes=28, watched_episodes=28)
            ],
            "series_path": lambda self, series_id: series_dir,
        },
    )()


def test_cleanup_command_default_is_dry_run_and_prints_preview(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    cleanup_settings = _jellyfin_settings(settings)
    series_dir = cleanup_settings.media_path / "Frieren"
    series_dir.mkdir(parents=True)
    (series_dir / "ep01.mkv").write_bytes(b"data")

    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: cleanup_settings))
    monkeypatch.setattr(cli, "JellyfinClient", _fake_client_factory(series_dir))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "cleanup"])

    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert series_dir.exists()
    assert "top-secret-key" not in out


def test_cleanup_command_json_reports_documented_shape(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    cleanup_settings = _jellyfin_settings(settings)
    series_dir = cleanup_settings.media_path / "Frieren"
    series_dir.mkdir(parents=True)
    (series_dir / "ep01.mkv").write_bytes(b"data")

    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: cleanup_settings))
    monkeypatch.setattr(cli, "JellyfinClient", _fake_client_factory(series_dir))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "cleanup", "--json"])

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["executed"] is False
    assert payload["deletable"] == 1
    assert payload["items"][0]["series_name"] == "Frieren"
    assert series_dir.exists()


def test_cleanup_command_missing_config_exits_nonzero_without_leaking_key(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_settings = replace(settings, jellyfin_api_key="top-secret-key", jellyfin_user_id="")
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: bad_settings))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "cleanup"])

    assert cli.main() != 0
    out = capsys.readouterr().out
    assert "top-secret-key" not in out


def test_cleanup_command_execute_yes_deletes_via_cli(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    cleanup_settings = _jellyfin_settings(settings)
    series_dir = cleanup_settings.media_path / "Frieren"
    series_dir.mkdir(parents=True)
    (series_dir / "ep01.mkv").write_bytes(b"data")

    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: cleanup_settings))
    monkeypatch.setattr(cli, "JellyfinClient", _fake_client_factory(series_dir))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "cleanup", "--execute", "--yes"])

    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "EXECUTED" in out
    assert not series_dir.exists()
