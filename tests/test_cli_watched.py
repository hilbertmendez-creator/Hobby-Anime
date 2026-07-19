import json
import sys

import pytest

import hobby_anime.cli as cli
from hobby_anime.config import Settings
from hobby_anime.models import WatchedEpisode, WatchedSeries


def _jellyfin_settings(settings: Settings) -> Settings:
    from dataclasses import replace

    return replace(
        settings,
        jellyfin_api_key="top-secret-key",
        jellyfin_user_id="user-1",
    )


def test_watched_command_prints_human_readable_table_by_default(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    watched_settings = _jellyfin_settings(settings)
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: watched_settings))
    monkeypatch.setattr(
        cli,
        "JellyfinClient",
        lambda *args, **kwargs: type(
            "FakeClient",
            (),
            {
                "list_watched_series": lambda self: [
                    WatchedSeries(id="s1", name="Frieren", total_episodes=28, watched_episodes=12)
                ]
            },
        )(),
    )
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "watched"])

    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "Frieren" in out
    assert "12" in out
    assert "28" in out
    assert "top-secret-key" not in out


def test_watched_command_json_output_matches_documented_shape(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    watched_settings = _jellyfin_settings(settings)
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: watched_settings))
    monkeypatch.setattr(
        cli,
        "JellyfinClient",
        lambda *args, **kwargs: type(
            "FakeClient",
            (),
            {
                "list_watched_series": lambda self: [
                    WatchedSeries(id="s1", name="Frieren", total_episodes=28, watched_episodes=12)
                ]
            },
        )(),
    )
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "watched", "--json"])

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["series"][0]["series_id"] == "s1"
    assert payload["series"][0]["series_name"] == "Frieren"
    assert payload["series"][0]["episodes_total"] == 28
    assert payload["series"][0]["episodes_watched"] == 12
    assert not payload["series"][0].get("episodes")


def test_watched_command_with_series_flag_includes_episodes(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    watched_settings = _jellyfin_settings(settings)
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: watched_settings))
    monkeypatch.setattr(
        cli,
        "JellyfinClient",
        lambda *args, **kwargs: type(
            "FakeClient",
            (),
            {
                "list_watched_series": lambda self: [
                    WatchedSeries(id="s1", name="Frieren", total_episodes=28, watched_episodes=12)
                ],
                "episodes": lambda self, series_id: [
                    WatchedEpisode(id="e1", name="Episode 1", played=True)
                ],
            },
        )(),
    )
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "watched", "--json", "--series", "s1"])

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["series"][0]["episodes"] == [
        {"episode_id": "e1", "episode_name": "Episode 1", "played": True}
    ]


def test_watched_command_missing_user_id_exits_nonzero_without_leaking_key(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    from dataclasses import replace

    bad_settings = replace(
        settings,
        jellyfin_api_key="top-secret-key",
        jellyfin_user_id="",
    )
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: bad_settings))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "watched"])

    assert cli.main() != 0
    out = capsys.readouterr().out
    assert "top-secret-key" not in out


def test_watched_command_missing_user_id_json_mode_reports_error(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    from dataclasses import replace

    bad_settings = replace(
        settings,
        jellyfin_api_key="top-secret-key",
        jellyfin_user_id="",
    )
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: bad_settings))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "watched", "--json"])

    assert cli.main() != 0
    payload = json.loads(capsys.readouterr().out)
    assert "error" in payload
    assert "top-secret-key" not in payload["error"]
