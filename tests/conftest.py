from pathlib import Path

import pytest

from hobby_anime.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    media_path = tmp_path / "media"
    media_path.mkdir()
    return Settings(
        database_path=tmp_path / "config" / "tracking.db",
        media_path=media_path,
        rss_urls=("https://example.test/feed.xml",),
        rss_resolution="1080p",
        rss_groups=(),
        rss_include_terms=(),
        rss_exclude_terms=(),
        rss_max_age_hours=72,
        qbt_host="qbittorrent",
        qbt_port=8080,
        qbt_username="admin",
        qbt_password="secret",
        qbt_save_path="/data/torrents",
        qbt_category="hobby-anime",
        daily_hour=3,
        daily_minute=0,
        monthly_day=1,
        monthly_hour=9,
        timezone="UTC",
        anilist_url="https://graphql.anilist.co",
        ollama_enabled=False,
        ollama_url="http://ollama:11434",
        ollama_model="qwen2.5:3b",
        webhook_url="",
        telegram_bot_token="",
        telegram_chat_id="",
        jellyfin_url="http://jellyfin:8096",
        request_timeout_seconds=5,
    )
