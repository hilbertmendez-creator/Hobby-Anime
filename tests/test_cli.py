import sys
from pathlib import Path
from types import SimpleNamespace

import hobby_anime.cli as cli
from hobby_anime.config import Settings
from hobby_anime.manual_review import ApprovalError
from hobby_anime.models import RejectedDownload


def test_parser_parses_approve_hashes() -> None:
    args = cli.build_parser().parse_args(["approve", "h1", "h2"])
    assert args.command == "approve"
    assert args.hashes == ["h1", "h2"]


def test_parser_rejections_json_flag() -> None:
    args = cli.build_parser().parse_args(["rejections", "--json"])
    assert args.command == "rejections"
    assert args.json is True


def test_approve_command_returns_nonzero_when_a_hash_fails(
    monkeypatch, settings: Settings
) -> None:
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: settings))
    calls: list[str] = []

    def fake_approve(_settings: Settings, torrent_hash: str, **_kwargs: object):
        calls.append(torrent_hash)
        if torrent_hash == "bad":
            raise ApprovalError("not a rejected download")
        return SimpleNamespace(name="ok")

    monkeypatch.setattr(cli, "approve_rejection", fake_approve)
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "approve", "good", "bad"])

    assert cli.main() == 1
    assert calls == ["good", "bad"]


def test_rejections_command_prints_and_returns_zero(
    monkeypatch, settings: Settings, capsys
) -> None:
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: settings))
    monkeypatch.setattr(
        cli,
        "list_rejections",
        lambda _settings: [
            RejectedDownload(
                "hash-bad",
                "Rejected show",
                "No Spanish tracks",
                Path("/q/bad.mkv"),
                "2026-07-19T00:00:00",
            )
        ],
    )
    monkeypatch.setattr(sys, "argv", ["hobby-anime", "rejections"])

    assert cli.main() == 0
    assert "hash-bad" in capsys.readouterr().out
