from datetime import UTC, datetime

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
