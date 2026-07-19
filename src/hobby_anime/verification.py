from __future__ import annotations

import logging
import math
from pathlib import Path

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.library_import import run_pending_imports
from hobby_anime.media_inspector import FfprobeInspector
from hobby_anime.models import VerificationRunResult
from hobby_anime.notifications import Notifier
from hobby_anime.qbittorrent_client import QBittorrentGateway
from hobby_anime.sonarr_client import SonarrClient

LOGGER = logging.getLogger(__name__)

MINIMUM_STALE_MINUTES = 30
STALE_MARGIN_MINUTES = 5


def _verification_stale_minutes(settings: Settings) -> int:
    """Derive claim staleness from the ffprobe timeout so slow inspections
    aren't preempted mid-run, with a floor matching the prior hardcoded default."""
    computed = math.ceil(settings.ffprobe_timeout_seconds / 60) + STALE_MARGIN_MINUTES
    return max(MINIMUM_STALE_MINUTES, computed)


def run_verification(
    settings: Settings,
    *,
    gateway: QBittorrentGateway | None = None,
    inspector: FfprobeInspector | None = None,
    database: TrackingDatabase | None = None,
    sonarr_client: SonarrClient | None = None,
    notifier: Notifier | None = None,
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
        move_timeout_seconds=settings.qbt_move_timeout_seconds,
    )
    inspector = inspector or FfprobeInspector(
        settings.ffprobe_path,
        settings.spanish_subtitle_exclude_terms,
        settings.ffprobe_timeout_seconds,
    )
    downloads = gateway.completed(settings.qbt_verify_categories)
    result = VerificationRunResult(discovered=len(downloads))
    stale_after_minutes = _verification_stale_minutes(settings)

    for download in downloads:
        if not database.claim_verification(download, stale_after_minutes=stale_after_minutes):
            result.skipped += 1
            continue
        try:
            _ensure_quarantine_path(download.content_path, Path(settings.qbt_save_path))
            inspection = inspector.inspect(download.content_path)
            if inspection.accepted:
                promoted = gateway.accept(
                    download.torrent_hash,
                    settings.qbt_verified_path,
                    settings.qbt_verified_category,
                )
                database.record_verification(promoted, "verified", inspection)
                result.verified += 1
                LOGGER.info("Spanish media verified: %s", download.name)
                if settings.sonarr_enabled and settings.sonarr_import_after_verify:
                    try:
                        database.queue_import(promoted)
                    except Exception as exc:
                        result.import_failed += 1
                        result.errors.append(f"{download.name}: {exc}")
                        LOGGER.exception(
                            "Could not queue verified download for Sonarr: %s",
                            download.name,
                        )
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

    if settings.notify_on_verification and (
        result.verified or result.rejected or result.failed
    ):
        notifier = notifier or Notifier(
            settings.webhook_url,
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            settings.request_timeout_seconds,
        )
        notifier.send(
            "\n".join(
                (
                    "Hobby-Anime verification report",
                    f"Verified: {result.verified}",
                    f"Rejected: {result.rejected}",
                    f"Failed: {result.failed}",
                    *result.errors[:10],
                )
            )
        )

    import_result = run_pending_imports(
        settings,
        client=sonarr_client,
        database=database,
        notifier=notifier,
    )
    result.imported = import_result.imported
    result.import_failed += import_result.failed
    result.errors.extend(import_result.errors)

    LOGGER.info(
        "Verification completed: discovered=%d verified=%d rejected=%d imported=%d "
        "import_failed=%d skipped=%d failed=%d",
        result.discovered,
        result.verified,
        result.rejected,
        result.imported,
        result.import_failed,
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
