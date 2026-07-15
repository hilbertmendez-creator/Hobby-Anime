from __future__ import annotations

import logging

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.models import ImportRunResult
from hobby_anime.notifications import Notifier
from hobby_anime.sonarr_client import SonarrClient, SonarrCommandFailed

LOGGER = logging.getLogger(__name__)


def run_pending_imports(
    settings: Settings,
    *,
    client: SonarrClient | None = None,
    database: TrackingDatabase | None = None,
    notifier: Notifier | None = None,
) -> ImportRunResult:
    result = ImportRunResult()
    if not settings.sonarr_enabled or not settings.sonarr_import_after_verify:
        return result
    if not settings.sonarr_api_key:
        raise ValueError("SONARR_API_KEY is required for library imports")

    database = database or TrackingDatabase(settings.database_path)
    database.initialize()
    client = client or SonarrClient(
        settings.sonarr_url,
        settings.sonarr_api_key,
        settings.request_timeout_seconds,
    )
    downloads = database.pending_imports()
    result.discovered = len(downloads)

    for download in downloads:
        if not database.claim_import(download):
            result.skipped += 1
            continue
        command_id = database.import_command_id(download.torrent_hash)
        try:
            if command_id is None:
                command_id = client.scan_verified(
                    download.content_path,
                    settings.sonarr_verified_root,
                    download.torrent_hash,
                )
                database.record_import(download.torrent_hash, "queued", command_id)
            client.wait_for_command(
                command_id,
                settings.sonarr_import_timeout_seconds,
                settings.sonarr_poll_seconds,
            )
            database.record_import(download.torrent_hash, "imported", command_id)
            result.imported += 1
            LOGGER.info("Sonarr imported verified download: %s", download.name)
        except SonarrCommandFailed as exc:
            database.record_import(
                download.torrent_hash,
                "error",
                None,
                str(exc),
            )
            result.failed += 1
            result.errors.append(f"{download.name}: {exc}")
            LOGGER.exception("Sonarr could not import verified download: %s", download.name)
        except Exception as exc:
            database.record_import(
                download.torrent_hash,
                "queued" if command_id is not None else "error",
                command_id,
                str(exc),
            )
            result.failed += 1
            result.errors.append(f"{download.name}: {exc}")
            LOGGER.exception("Sonarr import check failed: %s", download.name)

    if settings.notify_on_import and (result.imported or result.failed):
        notifier = notifier or Notifier(
            settings.webhook_url,
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            settings.request_timeout_seconds,
        )
        notifier.send(
            "\n".join(
                (
                    "Hobby-Anime import report",
                    f"Imported: {result.imported}",
                    f"Failed: {result.failed}",
                    *result.errors[:10],
                )
            )
        )
    return result
