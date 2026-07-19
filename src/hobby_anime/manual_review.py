from __future__ import annotations

import logging

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.models import RejectedDownload
from hobby_anime.qbittorrent_client import QBittorrentGateway

LOGGER = logging.getLogger(__name__)


class ApprovalError(ValueError):
    """Raised when a hash cannot be approved (unknown or not in 'rejected')."""


def _database(settings: Settings, database: TrackingDatabase | None) -> TrackingDatabase:
    database = database or TrackingDatabase(settings.database_path)
    database.initialize()
    return database


def list_rejections(
    settings: Settings,
    *,
    database: TrackingDatabase | None = None,
) -> list[RejectedDownload]:
    return _database(settings, database).rejected_downloads()


def approve_rejection(
    settings: Settings,
    torrent_hash: str,
    *,
    gateway: QBittorrentGateway | None = None,
    database: TrackingDatabase | None = None,
) -> RejectedDownload:
    if not settings.qbt_password:
        raise ValueError("QBITTORRENT_PASSWORD is required")

    database = _database(settings, database)
    matches = database.rejected_downloads(torrent_hash)
    if not matches:
        raise ApprovalError(f"{torrent_hash} is not a rejected download")
    rejected = matches[0]

    gateway = gateway or QBittorrentGateway(
        settings.qbt_host,
        settings.qbt_port,
        settings.qbt_username,
        settings.qbt_password,
        settings.qbt_save_path,
        settings.qbt_category,
        move_timeout_seconds=settings.qbt_move_timeout_seconds,
    )
    promoted = gateway.accept(
        torrent_hash,
        settings.qbt_verified_path,
        settings.qbt_verified_category,
        resume=True,
    )
    database.record_verification(
        promoted,
        "verified",
        reason=f"Manually approved (was rejected: {rejected.reason})",
    )
    if settings.sonarr_enabled and settings.sonarr_import_after_verify:
        database.queue_import(promoted)
    LOGGER.info("Manually approved rejected download: %s", rejected.name)
    return rejected
