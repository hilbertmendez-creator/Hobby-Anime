from __future__ import annotations

import logging
import shutil
from pathlib import Path

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.models import DailyRunResult
from hobby_anime.notifications import Notifier
from hobby_anime.qbittorrent_client import QBittorrentGateway
from hobby_anime.rss import RssReader, filter_items

LOGGER = logging.getLogger(__name__)


def run_daily(
    settings: Settings,
    *,
    dry_run: bool = False,
    reader: RssReader | None = None,
    gateway: QBittorrentGateway | None = None,
    database: TrackingDatabase | None = None,
    notifier: Notifier | None = None,
) -> DailyRunResult:
    if not settings.rss_enabled:
        LOGGER.info("Daily RSS agent is disabled")
        return DailyRunResult()
    settings.validate_daily(dry_run=dry_run)
    if not dry_run and settings.minimum_free_space_gb:
        quarantine = Path(settings.qbt_save_path)
        if not quarantine.is_dir():
            raise FileNotFoundError(f"Quarantine directory does not exist: {quarantine}")
        free_gb = shutil.disk_usage(quarantine).free / (1024**3)
        if free_gb < settings.minimum_free_space_gb:
            raise RuntimeError(
                f"Insufficient free space: {free_gb:.1f} GiB available, "
                f"{settings.minimum_free_space_gb} GiB required"
            )

    database = database or TrackingDatabase(settings.database_path)
    database.initialize()
    reader = reader or RssReader(settings.request_timeout_seconds)
    discovered = reader.fetch(settings.rss_urls)
    matches = filter_items(
        discovered,
        resolution=settings.rss_resolution,
        groups=settings.rss_groups,
        include_terms=settings.rss_include_terms,
        exclude_terms=settings.rss_exclude_terms,
        spanish_only=settings.spanish_only,
        spanish_language_terms=settings.spanish_language_terms,
        spanish_negative_terms=settings.spanish_negative_terms,
        spanish_trusted_groups=settings.spanish_trusted_groups,
        max_age_hours=settings.rss_max_age_hours,
    )
    result = DailyRunResult(discovered=len(discovered), matched=len(matches))

    if gateway is None and not dry_run:
        gateway = QBittorrentGateway(
            settings.qbt_host,
            settings.qbt_port,
            settings.qbt_username,
            settings.qbt_password,
            settings.qbt_save_path,
            settings.qbt_category,
        )

    for item in matches:
        if database.was_added(item.fingerprint):
            result.skipped += 1
            continue
        if dry_run:
            LOGGER.info("Dry run match: %s", item.title)
            result.skipped += 1
            continue
        try:
            assert gateway is not None
            gateway.add(item.download_url)
            database.record_added(item)
            result.added += 1
            LOGGER.info("Added to qBittorrent: %s", item.title)
        except Exception as exc:
            message = f"{item.title}: {exc}"
            database.record_error(item, str(exc))
            result.failed += 1
            result.errors.append(message)
            LOGGER.exception("Could not add RSS item: %s", item.title)

    LOGGER.info(
        "Daily run completed: discovered=%d matched=%d added=%d skipped=%d failed=%d",
        result.discovered,
        result.matched,
        result.added,
        result.skipped,
        result.failed,
    )
    if settings.notify_on_daily and (result.added or result.failed):
        notifier = notifier or Notifier(
            settings.webhook_url,
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            settings.request_timeout_seconds,
        )
        notifier.send(
            "\n".join(
                (
                    "Hobby-Anime daily report",
                    f"Added to quarantine: {result.added}",
                    f"Failed: {result.failed}",
                    *result.errors[:10],
                )
            )
        )
    return result
