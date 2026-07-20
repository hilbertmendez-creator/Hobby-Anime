from __future__ import annotations

import json
import sys
from dataclasses import replace

import pytest

import hobby_anime.cli as cli
from hobby_anime.config import Settings
from hobby_anime.models import AniListPushCandidate, AniListPushReport

DUMMY_TOKEN = "top-secret-anilist-access-token"  # noqa: S105


def _anilist_settings(settings: Settings) -> Settings:
    return replace(
        settings,
        anilist_client_id="client-123",
        anilist_client_secret="top-secret-client-secret",  # noqa: S106
        anilist_redirect_port=8712,
        status_api_port=8787,
    )


def _pushed_report() -> AniListPushReport:
    candidate = AniListPushCandidate(
        series_id="s1",
        series_name="Frieren",
        media_id=101,
        source="auto",
        status="COMPLETED",
        progress=28,
        skip_reason="",
    )
    return AniListPushReport(
        pushed=1,
        skipped_unchanged=0,
        skipped_unmapped=0,
        failed=0,
        candidates=(candidate,),
        errors=(),
        executed=False,
    )


def test_push_anilist_default_is_dry_run_and_never_calls_execute_true(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    push_settings = _anilist_settings(settings)
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: push_settings))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "push-anilist"])

    captured_kwargs: dict = {}

    def fake_run_push(passed_settings, database, **kwargs):
        captured_kwargs.update(kwargs)
        assert passed_settings is push_settings
        return _pushed_report()

    monkeypatch.setattr(cli, "run_push", fake_run_push)

    assert cli.main() == 0
    out = capsys.readouterr().out
    assert captured_kwargs["execute"] is False
    assert "DRY-RUN" in out
    assert DUMMY_TOKEN not in out


def test_push_anilist_json_reports_documented_shape(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    push_settings = _anilist_settings(settings)
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: push_settings))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "push-anilist", "--json"])
    monkeypatch.setattr(cli, "run_push", lambda passed_settings, database, **kwargs: _pushed_report())

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pushed"] == 1
    assert payload["candidates"][0]["series_name"] == "Frieren"
    assert payload["candidates"][0]["media_id"] == 101


def test_push_anilist_execute_without_yes_requires_confirmation(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    push_settings = _anilist_settings(settings)
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: push_settings))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "push-anilist", "--execute"])

    captured_kwargs: dict = {}

    def fake_run_push(passed_settings, database, **kwargs):
        captured_kwargs.update(kwargs)
        return replace(_pushed_report(), executed=False)

    monkeypatch.setattr(cli, "run_push", fake_run_push)

    assert cli.main() == 0
    assert captured_kwargs["execute"] is True
    assert captured_kwargs["assume_yes"] is False


def test_push_anilist_execute_yes_bypasses_prompt_and_reports_executed(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    push_settings = _anilist_settings(settings)
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: push_settings))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "push-anilist", "--execute", "--yes"])

    captured_kwargs: dict = {}

    def fake_run_push(passed_settings, database, **kwargs):
        captured_kwargs.update(kwargs)
        return replace(_pushed_report(), executed=True)

    monkeypatch.setattr(cli, "run_push", fake_run_push)

    assert cli.main() == 0
    out = capsys.readouterr().out
    assert captured_kwargs["assume_yes"] is True
    assert "EXECUTED" in out


def test_push_anilist_progress_flag_passed_through(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    push_settings = _anilist_settings(settings)
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: push_settings))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "push-anilist", "--progress"])

    captured_kwargs: dict = {}

    def fake_run_push(passed_settings, database, **kwargs):
        captured_kwargs.update(kwargs)
        return _pushed_report()

    monkeypatch.setattr(cli, "run_push", fake_run_push)

    assert cli.main() == 0
    assert captured_kwargs["progress_mode"] is True


def test_push_anilist_missing_token_error_exits_nonzero_without_leaking(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    push_settings = _anilist_settings(settings)
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: push_settings))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "push-anilist"])

    def raising_run_push(passed_settings, database, **kwargs):
        raise ValueError(
            "No valid AniList token found. Run 'hobby-anime anilist-auth' to authorize."
        )

    monkeypatch.setattr(cli, "run_push", raising_run_push)

    assert cli.main() == 1
    out = capsys.readouterr().out
    assert "anilist-auth" in out
    assert DUMMY_TOKEN not in out


def test_push_anilist_failed_items_exit_nonzero(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    push_settings = _anilist_settings(settings)
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: push_settings))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "push-anilist", "--execute", "--yes"])

    def fake_run_push(passed_settings, database, **kwargs):
        return replace(_pushed_report(), pushed=0, failed=1, executed=True, errors=("boom",))

    monkeypatch.setattr(cli, "run_push", fake_run_push)

    assert cli.main() == 1
