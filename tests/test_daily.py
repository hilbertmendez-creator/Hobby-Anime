from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hobby_anime.config import Settings
from hobby_anime.daily import run_daily
from hobby_anime.models import FeedItem


class FakeReader:
    def __init__(self, items: list[FeedItem]) -> None:
        self.items = items

    def fetch(self, urls: tuple[str, ...]) -> list[FeedItem]:
        return self.items


class FakeGateway:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def add(self, download_url: str) -> None:
        self.urls.append(download_url)


def test_daily_run_adds_once(settings: Settings) -> None:
    item = FeedItem(
        "fingerprint",
        "Example series - 01 [1080p] [Sub Español]",
        "magnet:?xt=example",
        datetime.now(UTC),
    )
    reader = FakeReader([item])
    gateway = FakeGateway()

    first = run_daily(settings, reader=reader, gateway=gateway)
    second = run_daily(settings, reader=reader, gateway=gateway)

    assert first.added == 1
    assert second.skipped == 1
    assert gateway.urls == ["magnet:?xt=example"]


def test_daily_dry_run_does_not_enqueue(settings: Settings) -> None:
    item = FeedItem(
        "fingerprint",
        "Example [1080p] [Sub Español]",
        "magnet:?xt=example",
    )
    gateway = FakeGateway()

    result = run_daily(settings, dry_run=True, reader=FakeReader([item]), gateway=gateway)

    assert result.matched == 1
    assert result.skipped == 1
    assert gateway.urls == []


def test_daily_blocks_download_when_storage_is_low(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    configured = replace(
        settings,
        qbt_save_path=str(quarantine),
        minimum_free_space_gb=100,
    )
    monkeypatch.setattr(
        "hobby_anime.daily.shutil.disk_usage",
        lambda _: type("Usage", (), {"free": 10 * 1024**3})(),
    )

    with pytest.raises(RuntimeError, match="Insufficient free space"):
        run_daily(configured, reader=FakeReader([]), gateway=FakeGateway())


def test_daily_can_be_disabled_for_sonarr_only_mode(settings: Settings) -> None:
    result = run_daily(replace(settings, rss_enabled=False))

    assert result.discovered == 0
    assert result.added == 0
