from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(value.strip() for value in os.getenv(name, default).split(",") if value.strip())


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class Settings:
    database_path: Path
    media_path: Path
    rss_urls: tuple[str, ...]
    rss_resolution: str
    rss_groups: tuple[str, ...]
    rss_include_terms: tuple[str, ...]
    rss_exclude_terms: tuple[str, ...]
    rss_max_age_hours: int
    qbt_host: str
    qbt_port: int
    qbt_username: str
    qbt_password: str
    qbt_save_path: str
    qbt_category: str
    daily_hour: int
    daily_minute: int
    monthly_day: int
    monthly_hour: int
    timezone: str
    anilist_url: str
    ollama_enabled: bool
    ollama_url: str
    ollama_model: str
    webhook_url: str
    telegram_bot_token: str
    telegram_chat_id: str
    jellyfin_url: str
    request_timeout_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=Path(os.getenv("DATABASE_PATH", "/config/hobby-anime.db")),
            media_path=Path(os.getenv("MEDIA_PATH", "/data/media")),
            rss_urls=_csv("RSS_URLS"),
            rss_resolution=os.getenv("RSS_RESOLUTION", "1080p").strip(),
            rss_groups=_csv("RSS_GROUPS"),
            rss_include_terms=_csv("RSS_INCLUDE_TERMS"),
            rss_exclude_terms=_csv("RSS_EXCLUDE_TERMS"),
            rss_max_age_hours=_int("RSS_MAX_AGE_HOURS", 72),
            qbt_host=os.getenv("QBITTORRENT_HOST", "qbittorrent").strip(),
            qbt_port=_int("QBITTORRENT_PORT", 8080),
            qbt_username=os.getenv("QBITTORRENT_USERNAME", "admin"),
            qbt_password=os.getenv("QBITTORRENT_PASSWORD", ""),
            qbt_save_path=os.getenv("QBITTORRENT_SAVE_PATH", "/data/torrents"),
            qbt_category=os.getenv("QBITTORRENT_CATEGORY", "hobby-anime"),
            daily_hour=_int("DAILY_HOUR", 3),
            daily_minute=_int("DAILY_MINUTE", 0),
            monthly_day=_int("MONTHLY_DAY", 1),
            monthly_hour=_int("MONTHLY_HOUR", 9),
            timezone=os.getenv("TZ", "UTC"),
            anilist_url=os.getenv("ANILIST_URL", "https://graphql.anilist.co"),
            ollama_enabled=_bool("OLLAMA_ENABLED"),
            ollama_url=os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
            webhook_url=os.getenv("WEBHOOK_URL", ""),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            jellyfin_url=os.getenv("JELLYFIN_URL", "http://jellyfin:8096").rstrip("/"),
            request_timeout_seconds=_int("REQUEST_TIMEOUT_SECONDS", 30),
        )

    def validate_daily(self) -> None:
        errors: list[str] = []
        if not self.rss_urls:
            errors.append("RSS_URLS is required")
        if not self.qbt_password:
            errors.append("QBITTORRENT_PASSWORD is required")
        if errors:
            raise ValueError("; ".join(errors))

    def validate_schedule(self) -> None:
        if not 0 <= self.daily_hour <= 23:
            raise ValueError("DAILY_HOUR must be between 0 and 23")
        if not 0 <= self.daily_minute <= 59:
            raise ValueError("DAILY_MINUTE must be between 0 and 59")
        if not 1 <= self.monthly_day <= 28:
            raise ValueError("MONTHLY_DAY must be between 1 and 28")
        if not 0 <= self.monthly_hour <= 23:
            raise ValueError("MONTHLY_HOUR must be between 0 and 23")
