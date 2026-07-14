from datetime import UTC, datetime, timedelta

from hobby_anime.models import FeedItem
from hobby_anime.rss import RssReader, filter_items


class FakeResponse:
    content = b"""
        <rss version="2.0"><channel><title>Authorized feed</title><item>
        <title>Public domain film [1080p]</title>
        <guid>item-1</guid>
        <link>https://example.test/download/film.torrent</link>
        <pubDate>Tue, 14 Jul 2026 10:00:00 GMT</pubDate>
        </item></channel></rss>
    """

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def get(self, url: str, **kwargs: object) -> FakeResponse:
        return FakeResponse()


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


def test_reader_parses_torrent_download_url() -> None:
    result = RssReader(session=FakeSession()).fetch(("https://example.test/feed.xml",))

    assert result[0].title == "Public domain film [1080p]"
    assert result[0].download_url.endswith("film.torrent")
    assert result[0].published_at == datetime(2026, 7, 14, 10, tzinfo=UTC)
