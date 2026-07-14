from datetime import UTC, datetime, timedelta

from hobby_anime.models import FeedItem
from hobby_anime.rss import filter_items


def test_filter_items_applies_all_rules() -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    items = [
        FeedItem("1", "[LegalGroup] Space Show - 01 [1080p]", "magnet:?xt=1", now),
        FeedItem("2", "[Other] Space Show - 01 [1080p]", "magnet:?xt=2", now),
        FeedItem("3", "[LegalGroup] Space Show - 01 [720p]", "magnet:?xt=3", now),
        FeedItem("4", "[LegalGroup] Space Show CAM [1080p]", "magnet:?xt=4", now),
        FeedItem("5", "[LegalGroup] Space Show - 00 [1080p]", "magnet:?xt=5", now - timedelta(days=5)),
    ]

    result = filter_items(
        items,
        resolution="1080p",
        groups=("LegalGroup",),
        include_terms=("Space Show",),
        exclude_terms=("CAM",),
        max_age_hours=72,
        now=now,
    )

    assert [item.fingerprint for item in result] == ["1"]


def test_filter_items_accepts_entries_without_publication_date() -> None:
    item = FeedItem("1", "Public domain film 1080p", "https://example.test/file.torrent")

    assert filter_items([item], max_age_hours=1) == [item]
