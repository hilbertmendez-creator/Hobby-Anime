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
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


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
    spanish_only: bool = True
    spanish_language_terms: tuple[str, ...] = (
        "spanish",
        "español",
        "castellano",
        "latino",
        "latam",
        "sub esp",
        "subesp",
        "spa",
    )
    spanish_negative_terms: tuple[str, ...] = (
        "raw",
        "english only",
        "no subs",
        "sin subtítulos",
    )
    spanish_trusted_groups: tuple[str, ...] = ()
    spanish_subtitle_exclude_terms: tuple[str, ...] = (
        "forced",
        "forzado",
        "forzados",
        "signs",
        "songs",
        "carteles",
        "canciones",
    )
    qbt_verified_path: str = "/data/torrents/verified"
    qbt_verified_category: str = "hobby-anime-verified"
    qbt_rejected_category: str = "hobby-anime-rejected"
    verification_interval_minutes: int = 10
    ffprobe_path: str = "ffprobe"
    ffprobe_timeout_seconds: int = 60
    qbt_move_timeout_seconds: int = 300
    qbt_verify_categories: tuple[str, ...] = ("hobby-anime",)
    sonarr_enabled: bool = False
    sonarr_url: str = "http://sonarr:8989"
    sonarr_api_key: str = ""
    sonarr_import_after_verify: bool = True
    sonarr_verified_root: Path = Path("/data/torrents/verified")
    sonarr_media_root: Path = Path("/data/media/anime")
    sonarr_import_timeout_seconds: int = 600
    sonarr_poll_seconds: int = 2
    prowlarr_enabled: bool = False
    prowlarr_url: str = "http://prowlarr:9696"
    prowlarr_api_key: str = ""
    bazarr_enabled: bool = False
    bazarr_url: str = "http://bazarr:6767"
    bazarr_api_key: str = ""
    notify_on_verification: bool = True
    notify_on_import: bool = True
    notify_on_daily: bool = True
    import_retry_interval_minutes: int = 30
    minimum_free_space_gb: int = 0
    rss_enabled: bool = True
    status_api_token: str = ""
    status_api_host: str = "0.0.0.0"
    status_api_port: int = 8787

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
            qbt_save_path=os.getenv("QBITTORRENT_SAVE_PATH", "/data/torrents/quarantine"),
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
            spanish_only=_bool("SPANISH_ONLY", True),
            spanish_language_terms=_csv(
                "SPANISH_LANGUAGE_TERMS",
                "spanish,español,castellano,latino,latam,sub esp,subesp,spa",
            ),
            spanish_negative_terms=_csv(
                "SPANISH_NEGATIVE_TERMS",
                "raw,english only,no subs,sin subtítulos",
            ),
            spanish_trusted_groups=_csv("SPANISH_TRUSTED_GROUPS"),
            spanish_subtitle_exclude_terms=_csv(
                "SPANISH_SUBTITLE_EXCLUDE_TERMS",
                "forced,forzado,forzados,signs,songs,carteles,canciones",
            ),
            qbt_verified_path=os.getenv(
                "QBITTORRENT_VERIFIED_PATH",
                "/data/torrents/verified",
            ),
            qbt_verified_category=os.getenv(
                "QBITTORRENT_VERIFIED_CATEGORY",
                "hobby-anime-verified",
            ),
            qbt_rejected_category=os.getenv(
                "QBITTORRENT_REJECTED_CATEGORY",
                "hobby-anime-rejected",
            ),
            verification_interval_minutes=_int("VERIFICATION_INTERVAL_MINUTES", 10),
            ffprobe_path=os.getenv("FFPROBE_PATH", "ffprobe"),
            ffprobe_timeout_seconds=_int("FFPROBE_TIMEOUT_SECONDS", 60),
            qbt_move_timeout_seconds=_int("QBITTORRENT_MOVE_TIMEOUT_SECONDS", 300),
            qbt_verify_categories=_csv(
                "QBITTORRENT_VERIFY_CATEGORIES",
                os.getenv("QBITTORRENT_CATEGORY", "hobby-anime"),
            ),
            sonarr_enabled=_bool("SONARR_ENABLED", False),
            sonarr_url=os.getenv("SONARR_URL", "http://sonarr:8989").rstrip("/"),
            sonarr_api_key=os.getenv("SONARR_API_KEY", ""),
            sonarr_import_after_verify=_bool("SONARR_IMPORT_AFTER_VERIFY", True),
            sonarr_verified_root=Path(
                os.getenv("SONARR_VERIFIED_ROOT", "/data/torrents/verified")
            ),
            sonarr_media_root=Path(
                os.getenv("SONARR_MEDIA_ROOT", "/data/media/anime")
            ),
            sonarr_import_timeout_seconds=_int(
                "SONARR_IMPORT_TIMEOUT_SECONDS",
                600,
            ),
            sonarr_poll_seconds=_int("SONARR_POLL_SECONDS", 2),
            prowlarr_enabled=_bool("PROWLARR_ENABLED", False),
            prowlarr_url=os.getenv(
                "PROWLARR_URL",
                "http://prowlarr:9696",
            ).rstrip("/"),
            prowlarr_api_key=os.getenv("PROWLARR_API_KEY", ""),
            bazarr_enabled=_bool("BAZARR_ENABLED", False),
            bazarr_url=os.getenv("BAZARR_URL", "http://bazarr:6767").rstrip("/"),
            bazarr_api_key=os.getenv("BAZARR_API_KEY", ""),
            notify_on_verification=_bool("NOTIFY_ON_VERIFICATION", True),
            notify_on_import=_bool("NOTIFY_ON_IMPORT", True),
            notify_on_daily=_bool("NOTIFY_ON_DAILY", True),
            import_retry_interval_minutes=_int(
                "IMPORT_RETRY_INTERVAL_MINUTES",
                30,
            ),
            minimum_free_space_gb=_int("MINIMUM_FREE_SPACE_GB", 100),
            rss_enabled=_bool("RSS_ENABLED", True),
            status_api_token=os.getenv("STATUS_API_TOKEN", ""),
            status_api_host=os.getenv("STATUS_API_HOST", "0.0.0.0"),
            status_api_port=_int("STATUS_API_PORT", 8787),
        )

    def validate_daily(self, *, dry_run: bool = False) -> None:
        errors: list[str] = []
        if not self.rss_urls:
            errors.append("RSS_URLS is required")
        if not dry_run and not self.qbt_password:
            errors.append("QBITTORRENT_PASSWORD is required")
        if self.spanish_only and not (
            self.spanish_language_terms or self.spanish_trusted_groups
        ):
            errors.append(
                "SPANISH_LANGUAGE_TERMS or SPANISH_TRUSTED_GROUPS is required "
                "when SPANISH_ONLY is enabled"
            )
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
        if self.verification_interval_minutes < 1:
            raise ValueError("VERIFICATION_INTERVAL_MINUTES must be at least 1")
        if self.ffprobe_timeout_seconds < 1:
            raise ValueError("FFPROBE_TIMEOUT_SECONDS must be at least 1")
        if self.qbt_move_timeout_seconds < 1:
            raise ValueError("QBITTORRENT_MOVE_TIMEOUT_SECONDS must be at least 1")
        if self.import_retry_interval_minutes < 1:
            raise ValueError("IMPORT_RETRY_INTERVAL_MINUTES must be at least 1")
        if self.sonarr_import_timeout_seconds < 1 or self.sonarr_poll_seconds < 1:
            raise ValueError("Sonarr import and poll timeouts must be at least 1")
        if self.sonarr_enabled and not self.sonarr_api_key:
            raise ValueError("SONARR_API_KEY is required when SONARR_ENABLED is true")
        if (
            self.sonarr_enabled
            and Path(self.qbt_verified_path) != self.sonarr_verified_root
        ):
            raise ValueError(
                "QBITTORRENT_VERIFIED_PATH and SONARR_VERIFIED_ROOT must match"
            )
        if self.prowlarr_enabled and not self.prowlarr_api_key:
            raise ValueError("PROWLARR_API_KEY is required when PROWLARR_ENABLED is true")
        if self.bazarr_enabled and not self.bazarr_api_key:
            raise ValueError("BAZARR_API_KEY is required when BAZARR_ENABLED is true")
        if self.minimum_free_space_gb < 0:
            raise ValueError("MINIMUM_FREE_SPACE_GB cannot be negative")
