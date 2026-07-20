from __future__ import annotations

import sys
from dataclasses import replace

import pytest

import hobby_anime.cli as cli
from hobby_anime.config import Settings
from hobby_anime.models import StoredToken

DUMMY_CLIENT_SECRET = "top-secret-anilist-client-secret"  # noqa: S105
DUMMY_TOKEN = "top-secret-anilist-access-token"  # noqa: S105


def _anilist_settings(settings: Settings) -> Settings:
    return replace(
        settings,
        anilist_client_id="client-123",
        anilist_client_secret=DUMMY_CLIENT_SECRET,
        anilist_redirect_port=8712,
        status_api_port=8787,
    )


def test_anilist_auth_command_success_prints_no_secret(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    ready_settings = _anilist_settings(settings)
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: ready_settings))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "anilist-auth"])

    saved: list[StoredToken] = []

    def fake_run_auth_flow(passed_settings, database, **kwargs):
        assert passed_settings is ready_settings
        token = StoredToken(
            access_token=DUMMY_TOKEN, token_type="Bearer", obtained_at="2026-07-19T00:00:00+00:00"
        )
        database.save_token(token)
        saved.append(token)
        return token

    monkeypatch.setattr(cli, "run_auth_flow", fake_run_auth_flow)

    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "successful" in out.lower()
    assert DUMMY_TOKEN not in out
    assert DUMMY_CLIENT_SECRET not in out
    assert len(saved) == 1


def test_anilist_auth_command_missing_client_id_fails_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_settings = replace(
        settings,
        anilist_client_id="",
        anilist_client_secret=DUMMY_CLIENT_SECRET,
        anilist_redirect_port=8712,
        status_api_port=8787,
    )
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: bad_settings))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "anilist-auth"])

    # Deliberately do NOT mock run_auth_flow: config validation must fail
    # inside it, before any browser/socket/network IO is attempted.
    def fail_if_reached(*_args, **_kwargs):
        raise AssertionError("browser open must not be reached before config validation")

    monkeypatch.setattr("webbrowser.open", fail_if_reached)

    assert cli.main() == 1
    out = capsys.readouterr().out
    assert "ANILIST_CLIENT_ID" in out
    assert DUMMY_CLIENT_SECRET not in out


def test_anilist_auth_command_upstream_failure_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    ready_settings = _anilist_settings(settings)
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: ready_settings))
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "anilist-auth"])

    def raising_run_auth_flow(passed_settings, database, **kwargs):
        # A well-behaved run_auth_flow never puts secrets in its exception
        # text (verified directly in tests/test_anilist_oauth.py); this test
        # only checks the CLI surfaces the failure with a non-zero exit.
        raise TimeoutError("Timed out waiting for the AniList OAuth callback")

    monkeypatch.setattr(cli, "run_auth_flow", raising_run_auth_flow)

    assert cli.main() == 1
    out = capsys.readouterr().out
    assert "error" in out.lower()
    assert DUMMY_CLIENT_SECRET not in out
