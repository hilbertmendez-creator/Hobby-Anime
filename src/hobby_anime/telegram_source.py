"""Telegram channel ingestion: filtering, quarantine verification and promotion.

This module holds the parts of the Telegram source that do not depend on
Telethon, so they can be tested without a network or an account. The live
listener lives in ``telegram_listener``.

Telegram downloads reuse the existing pipeline:

    channel message -> quarantine/<id>/<file> -> ffprobe Spanish policy
        -> verified/telegram/<id>/<file> -> library_import queue -> Sonarr

Each message is tracked in ``download_verification`` and ``library_import``
under a synthetic id ``tg-<chat>-<message>`` instead of a torrent hash.
"""

from __future__ import annotations

import logging
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Protocol

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.library import VIDEO_EXTENSIONS
from hobby_anime.models import MediaInspection, RejectedDownload, TorrentDownload
from hobby_anime.notifications import Notifier

LOGGER = logging.getLogger(__name__)

TELEGRAM_PREFIX = "tg-"
PARTIAL_SUFFIX = ".part"
MAX_FILENAME_LENGTH = 180
_UNSAFE_CHARACTERS = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]+')


class Inspector(Protocol):
    def inspect(self, content_path: Path) -> MediaInspection: ...


def is_telegram_id(value: str) -> bool:
    return value.startswith(TELEGRAM_PREFIX)


def message_fingerprint(chat_id: int, message_id: int) -> str:
    """Stable id for one channel message; channel ids are negative in Telethon."""
    return f"{TELEGRAM_PREFIX}{abs(int(chat_id))}-{int(message_id)}"


def safe_filename(name: str, fallback: str) -> str:
    """Reduce an untrusted Telegram file name to a single safe path component."""
    candidate = unicodedata.normalize("NFC", name or "").replace("\\", "/").rsplit("/", 1)[-1]
    candidate = _UNSAFE_CHARACTERS.sub(" ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" .")
    if not candidate or candidate in {".", ".."}:
        candidate = fallback
    if len(candidate) > MAX_FILENAME_LENGTH:
        path = Path(candidate)
        suffix = path.suffix[:16]
        candidate = path.stem[: MAX_FILENAME_LENGTH - len(suffix)].rstrip(" .") + suffix
    return candidate


def candidate_rejection(file_name: str, size_bytes: int | None, settings: Settings) -> str | None:
    """Return why a channel file should be skipped, or ``None`` to download it.

    These checks run before downloading so nothing unwanted touches the disk.
    The Spanish language policy is still enforced afterwards with ffprobe.
    """
    if Path(file_name).suffix.casefold() not in VIDEO_EXTENSIONS:
        return "not a supported video file"
    if size_bytes is None or size_bytes <= 0:
        return "unknown file size"
    if size_bytes < settings.telegram_min_file_mb * 1024**2:
        return f"smaller than {settings.telegram_min_file_mb} MB"
    if size_bytes > settings.telegram_max_file_gb * 1024**3:
        return f"larger than {settings.telegram_max_file_gb} GB"

    normalized = _normalize(file_name)
    for term in settings.telegram_exclude_terms:
        if _normalize(term) in normalized:
            return f"excluded term: {term}"
    if settings.spanish_only:
        for term in settings.spanish_negative_terms:
            if _normalize(term) in normalized:
                return f"Spanish policy negative term: {term}"
    missing = [term for term in settings.telegram_include_terms if _normalize(term) not in normalized]
    if missing:
        return f"missing required terms: {', '.join(missing)}"
    return None


def has_free_space(path: Path, minimum_gb: int, needed_bytes: int = 0) -> bool:
    if minimum_gb <= 0 and needed_bytes <= 0:
        return True
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    return free - needed_bytes >= minimum_gb * 1024**3


def quarantine_target(settings: Settings, fingerprint: str, file_name: str) -> Path:
    """Folder per message keeps names readable for Sonarr and avoids collisions."""
    return settings.telegram_quarantine_path / fingerprint / file_name


def verify_download(
    download: TorrentDownload,
    settings: Settings,
    *,
    inspector: Inspector,
    database: TrackingDatabase,
    notifier: Notifier | None = None,
) -> str:
    """Run the Spanish policy on a finished Telegram file and promote it.

    Returns the final status: ``verified``, ``rejected`` or ``error``.
    Rejected files stay in quarantine so ``hobby-anime approve`` can promote them.
    """
    try:
        _ensure_inside(download.content_path, settings.telegram_quarantine_path)
        inspection = inspector.inspect(download.content_path)
        if inspection.accepted:
            promoted = _promote(download, settings)
            database.record_verification(promoted, "verified", inspection)
            if settings.sonarr_enabled and settings.sonarr_import_after_verify:
                database.queue_import(promoted)
            LOGGER.info("Telegram media verified: %s", download.name)
            status, detail = "verified", inspection.reason
        else:
            database.record_verification(download, "rejected", inspection)
            LOGGER.warning(
                "Telegram media rejected by Spanish policy: %s (%s)",
                download.name,
                inspection.reason,
            )
            status, detail = "rejected", inspection.reason
    except Exception as exc:
        database.record_verification(download, "error", reason=str(exc))
        LOGGER.exception("Could not verify Telegram download: %s", download.name)
        status, detail = "error", str(exc)

    if notifier is not None and settings.notify_on_verification:
        try:
            notifier.send(f"Hobby-Anime Telegram: {status}\n{download.name}\n{detail}")
        except Exception:
            LOGGER.exception("Could not send Telegram source notification")
    return status


def approve_telegram_rejection(
    settings: Settings,
    rejected: RejectedDownload,
    database: TrackingDatabase,
) -> TorrentDownload:
    """Manual override for a rejected Telegram file (``hobby-anime approve tg-...``)."""
    download = TorrentDownload(rejected.torrent_hash, rejected.name, rejected.content_path)
    _ensure_inside(download.content_path, settings.telegram_quarantine_path)
    promoted = _promote(download, settings)
    database.record_verification(
        promoted,
        "verified",
        reason=f"Manually approved (was rejected: {rejected.reason})",
    )
    if settings.sonarr_enabled and settings.sonarr_import_after_verify:
        database.queue_import(promoted)
    return promoted


def _promote(download: TorrentDownload, settings: Settings) -> TorrentDownload:
    source = download.content_path
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError(f"Telegram download is missing or not a regular file: {source}")
    target = settings.telegram_verified_path / download.torrent_hash / source.name
    if target.exists():
        raise FileExistsError(f"Verified target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    try:
        source.parent.rmdir()
    except OSError:
        pass
    return TorrentDownload(download.torrent_hash, download.name, target)


def _ensure_inside(path: Path, root: Path) -> None:
    resolved = path.resolve()
    resolved_root = root.resolve()
    if resolved_root not in resolved.parents:
        raise ValueError(f"Telegram file is outside quarantine: {path}")


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))
