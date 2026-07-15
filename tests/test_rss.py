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


def test_spanish_policy_uses_or_terms_and_rejects_negative_markers() -> None:
    items = [
        FeedItem("1", "Show - 01 [1080p] [Sub Español]", "magnet:?xt=1"),
        FeedItem("2", "Show - 02 [1080p] [Castellano]", "magnet:?xt=2"),
        FeedItem("3", "Show - 03 [1080p] [English]", "magnet:?xt=3"),
        FeedItem("4", "Show - 04 [1080p] [RAW] [SPA]", "magnet:?xt=4"),
        FeedItem("5", "Space Show - 05 [1080p]", "magnet:?xt=5"),
    ]

    result = filter_items(
        items,
        spanish_only=True,
        spanish_language_terms=("español", "castellano", "spa"),
        spanish_negative_terms=("raw",),
    )

    assert [item.fingerprint for item in result] == ["1", "2"]


def test_spanish_policy_accepts_category_magnet_or_trusted_group() -> None:
    items = [
        FeedItem(
            "1",
            "Show - 01 [1080p]",
            "https://example.test/show.torrent",
            categories=("Subtítulos en español",),
        ),
        FeedItem(
            "2",
            "Show - 02 [1080p]",
            "magnet:?xt=urn:btih:test&dn=Show+02+SubESP",
        ),
        FeedItem(
            "3",
            "[TrustedES] Show - 03 [1080p]",
            "https://example.test/show-3.torrent",
        ),
    ]

    result = filter_items(
        items,
        spanish_only=True,
        spanish_language_terms=("español", "subesp"),
        spanish_trusted_groups=("TrustedES",),
    )

    assert [item.fingerprint for item in result] == ["1", "2", "3"]


def test_spanish_policy_does_not_trust_free_form_description() -> None:
    item = FeedItem(
        "1",
        "Documentary - 01 [1080p]",
        "https://example.test/documentary.torrent",
        description="A documentary about Spanish culture with English audio",
    )

    result = filter_items(
        [item],
        spanish_only=True,
        spanish_language_terms=("spanish",),
    )

    assert result == []
