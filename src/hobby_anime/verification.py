from __future__ import annotations

import logging
from pathlib import Path

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.media_inspector import FfprobeInspector
from hobby_anime.models import VerificationRunResult
from hobby_anime.qbittorrent_client import QBittorrentGateway

LOGGER = logging.getLogger(__name__)


def run_verification(
    settings: Settings,
    *,
    gateway: QBittorrentGateway | None = None,
    inspector: FfprobeInspector | None = None,
    database: TrackingDatabase | None = None,
) -> VerificationRunResult:
    if not settings.qbt_password:
        raise ValueError("QBITTORRENT_PASSWORD is required")

    database = database or TrackingDatabase(settings.database_path)
    database.initialize()
    gateway = gateway or QBittorrentGateway(
        settings.qbt_host,
        settings.qbt_port,
        settings.qbt_username,
        settings.qbt_password,
        settings.qbt_save_path,
        settings.qbt_category,
    )
    inspector = inspector or FfprobeInspector(
        settings.ffprobe_path,
        settings.spanish_subtitle_exclude_terms,
        settings.ffprobe_timeout_seconds,
    )
    downloads = gateway.completed()
    result = VerificationRunResult(discovered=len(downloads))

    for download in downloads:
        if database.verification_status(download.torrent_hash) in {"verified", "rejected"}:
            result.skipped += 1
            continue
        try:
            _ensure_quarantine_path(download.content_path, Path(settings.qbt_save_path))
            inspection = inspector.inspect(download.content_path)
            if inspection.accepted:
                gateway.accept(
                    download.torrent_hash,
                    settings.qbt_verified_path,
                    settings.qbt_verified_category,
                )
                database.record_verification(download, "verified", inspection)
                result.verified += 1
                LOGGER.info("Spanish media verified: %s", download.name)
            else:
                gateway.reject(download.torrent_hash, settings.qbt_rejected_category)
                database.record_verification(download, "rejected", inspection)
                result.rejected += 1
                LOGGER.warning(
                    "Download rejected by Spanish policy: %s (%s)",
                    download.name,
                    inspection.reason,
                )
        except Exception as exc:
            database.record_verification(download, "error", reason=str(exc))
            result.failed += 1
            result.errors.append(f"{download.name}: {exc}")
            LOGGER.exception("Could not verify completed download: %s", download.name)

    LOGGER.info(
        "Verification completed: discovered=%d verified=%d rejected=%d skipped=%d failed=%d",
        result.discovered,
        result.verified,
        result.rejected,
        result.skipped,
        result.failed,
    )
    return result


def _ensure_quarantine_path(content_path: Path, quarantine_path: Path) -> None:
    resolved_content = content_path.resolve()
    resolved_quarantine = quarantine_path.resolve()
    if (
        resolved_content != resolved_quarantine
        and resolved_quarantine not in resolved_content.parents
    ):
        raise ValueError(
            f"Completed download is outside the quarantine directory: {content_path}"
        )
