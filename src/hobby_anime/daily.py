from __future__ import annotations

import logging

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.models import DailyRunResult
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
) -> DailyRunResult:
    if not settings.rss_urls:
        raise ValueError("RSS_URLS is required")
    if not dry_run and not settings.qbt_password:
        raise ValueError("QBITTORRENT_PASSWORD is required")

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
    return result
