"""Live Telegram listener built on Telethon (MTProto user client).

A user session is required because the Bot API caps downloads at 20 MB and
bots cannot join channels they do not administer. Run ``hobby-anime
telegram-login`` once to create the session, then ``telegram-listen``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.media_inspector import FfprobeInspector
from hobby_anime.models import TorrentDownload
from hobby_anime.notifications import Notifier
from hobby_anime.telegram_source import (
    PARTIAL_SUFFIX,
    Inspector,
    candidate_rejection,
    has_free_space,
    message_fingerprint,
    quarantine_target,
    safe_filename,
    verify_download,
)
from hobby_anime.terabox import TeraBoxAuthError, TeraBoxClient, find_links

LOGGER = logging.getLogger(__name__)

# Large files can take a while; do not let a parallel run steal the claim mid-download.
CLAIM_STALE_MINUTES = 240
FLOOD_SLEEP_SECONDS = 300
AUTH_ALERT_INTERVAL_SECONDS = 6 * 3600

Downloader = Callable[[Any, Path], Awaitable[Any]]


class TelegramIngestor:
    """Decides, downloads and verifies one channel message at a time."""

    def __init__(
        self,
        settings: Settings,
        *,
        download: Downloader,
        database: TrackingDatabase,
        inspector: Inspector,
        notifier: Notifier | None = None,
        terabox: TeraBoxClient | None = None,
    ) -> None:
        self.settings = settings
        self.download = download
        self.database = database
        self.inspector = inspector
        self.notifier = notifier
        self.terabox = terabox
        self.semaphore = asyncio.Semaphore(settings.telegram_concurrent_downloads)
        self._last_auth_alert: float | None = None

    async def handle(self, message: Any) -> str:
        """Process one message and return a short outcome label.

        A message with several TeraBox files returns the label of the last file.
        """
        media = getattr(message, "file", None)
        if media is not None:
            fingerprint = message_fingerprint(message.chat_id, message.id)
            file_name = message_file_name(message, fingerprint)
            return await self._ingest(
                fingerprint,
                file_name,
                getattr(media, "size", None),
                lambda path: self.download(message, path),
            )

        if self.terabox is not None:
            links = find_links(getattr(message, "message", None) or "", message_urls(message))
            if links:
                return await self._handle_terabox(message, links)
        return "no-file"

    async def _handle_terabox(self, message: Any, links: list[str]) -> str:
        outcome = "filtered"
        base = message_fingerprint(message.chat_id, message.id)
        for link in links:
            try:
                files = await asyncio.to_thread(
                    self.terabox.resolve, link, self.settings.terabox_max_files_per_link
                )
            except TeraBoxAuthError as exc:
                await self._auth_alert(str(exc))
                return "error"
            except Exception:
                LOGGER.exception("Could not read TeraBox link from message %s", base)
                outcome = "error"
                continue
            for file in files:
                fingerprint = f"{base}-tb{file.fs_id}"
                name = safe_filename(file.name, f"{fingerprint}.mkv")
                outcome = await self._ingest(
                    fingerprint,
                    name,
                    file.size,
                    lambda path, file=file: asyncio.to_thread(self.terabox.download, file, path),
                )
        return outcome

    async def _ingest(
        self,
        fingerprint: str,
        file_name: str,
        size: int | None,
        fetch: Callable[[Path], Awaitable[Any]],
    ) -> str:
        reason = candidate_rejection(file_name, size, self.settings)
        if reason:
            LOGGER.debug("Skipping Telegram file %s: %s", file_name, reason)
            return "filtered"

        if not has_free_space(
            self.settings.telegram_quarantine_path,
            self.settings.minimum_free_space_gb,
            int(size or 0),
        ):
            LOGGER.warning("Not enough free space for Telegram file: %s", file_name)
            return "no-space"

        target = quarantine_target(self.settings, fingerprint, file_name)
        download = TorrentDownload(fingerprint, file_name, target)
        claimed = await asyncio.to_thread(
            self.database.claim_verification,
            download,
            CLAIM_STALE_MINUTES,
        )
        if not claimed:
            return "duplicate"

        async with self.semaphore:
            partial = target.with_name(target.name + PARTIAL_SUFFIX)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                LOGGER.info("Downloading Telegram file: %s (%.0f MB)", file_name, (size or 0) / 1024**2)
                await fetch(partial)
                if not partial.is_file() or partial.stat().st_size != size:
                    raise IOError("Telegram download is incomplete")
                partial.replace(target)
            except Exception as exc:
                _remove_partial(partial)
                await asyncio.to_thread(
                    self.database.record_verification,
                    download,
                    "error",
                    None,
                    f"Download failed: {exc}",
                )
                if isinstance(exc, TeraBoxAuthError):
                    await self._auth_alert(str(exc))
                LOGGER.exception("Telegram download failed: %s", file_name)
                return "error"

            return await asyncio.to_thread(
                verify_download,
                download,
                self.settings,
                inspector=self.inspector,
                database=self.database,
                notifier=self.notifier,
            )

    async def _auth_alert(self, detail: str) -> None:
        LOGGER.error("TeraBox authentication problem: %s", detail)
        now = time.monotonic()
        if self.notifier is None:
            return
        if self._last_auth_alert is not None and now - self._last_auth_alert < AUTH_ALERT_INTERVAL_SECONDS:
            return
        self._last_auth_alert = now
        try:
            await asyncio.to_thread(
                self.notifier.send,
                "Hobby-Anime TeraBox: la cookie ndus parece vencida o rechazada.\n"
                f"Actualiza TERABOX_COOKIE y reinicia hobby-anime-telegram.\n{detail}",
            )
        except Exception:
            LOGGER.exception("Could not send TeraBox alert")


def message_file_name(message: Any, fingerprint: str) -> str:
    """Prefer the uploaded file name; videos sent as media often have none."""
    media = message.file
    extension = (getattr(media, "ext", None) or "").strip()
    raw_name = getattr(media, "name", None) or ""
    if not raw_name:
        caption = (getattr(message, "message", None) or "").strip().splitlines()
        if caption and caption[0].strip():
            raw_name = caption[0].strip()[:150] + extension
    return safe_filename(raw_name, f"{fingerprint}{extension}")


def message_urls(message: Any) -> list[str]:
    """Hidden links (text with a URL behind it) live in message entities."""
    urls: list[str] = []
    for entity in getattr(message, "entities", None) or ():
        url = getattr(entity, "url", None)
        if url:
            urls.append(str(url))
    return urls


def parse_channel_ref(value: str) -> str | int:
    """Accept @name, name, t.me links or numeric ids like -1001234567890."""
    ref = value.strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if ref.casefold().startswith(prefix):
            ref = ref[len(prefix):]
    ref = ref.strip("/")
    if ref.lstrip("-").isdigit():
        return int(ref)
    return ref.lstrip("@")


def run_login(settings: Settings) -> int:
    settings.validate_telegram(for_login=True)
    return asyncio.run(_login(settings))


def run_listener(settings: Settings) -> None:
    settings.validate_telegram()
    asyncio.run(_listen(settings))


def _build_client(settings: Settings) -> Any:
    from telethon import TelegramClient

    settings.telegram_session_path.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(settings.telegram_session_path),
        settings.telegram_api_id,
        settings.telegram_api_hash,
        flood_sleep_threshold=FLOOD_SLEEP_SECONDS,
        device_model="Hobby-Anime NAS",
        app_version="hobby-anime",
    )


async def _login(settings: Settings) -> int:
    client = _build_client(settings)
    # start() prompts for phone, login code and 2FA password when needed.
    await client.start()
    try:
        me = await client.get_me()
        print(f"Session ready for: {getattr(me, 'first_name', '')} (id {me.id})")
        print("Channels this account can read (use the id or @name in TELEGRAM_CHANNELS):")
        async for dialog in client.iter_dialogs():
            if dialog.is_channel:
                username = getattr(dialog.entity, "username", None)
                handle = f"@{username}" if username else "-"
                print(f"  {dialog.id}\t{handle}\t{dialog.name}")
    finally:
        await client.disconnect()
    _restrict_session_file(settings)
    return 0


async def _listen(settings: Settings) -> None:
    from telethon import events

    client = _build_client(settings)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError(
            "Telegram session is not authorized; run "
            "`docker compose run --rm -it hobby-anime-telegram telegram-login` first"
        )
    _restrict_session_file(settings)

    database = TrackingDatabase(settings.database_path)
    database.initialize()
    settings.telegram_quarantine_path.mkdir(parents=True, exist_ok=True)
    ingestor = TelegramIngestor(
        settings,
        download=lambda message, path: client.download_media(message, file=str(path)),
        database=database,
        inspector=FfprobeInspector(
            settings.ffprobe_path,
            settings.spanish_subtitle_exclude_terms,
            settings.ffprobe_timeout_seconds,
        ),
        notifier=Notifier(
            settings.webhook_url,
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            settings.request_timeout_seconds,
        ),
        terabox=(
            TeraBoxClient(settings.terabox_cookie, timeout_seconds=settings.request_timeout_seconds)
            if settings.terabox_enabled
            else None
        ),
    )

    chats = [await client.get_entity(parse_channel_ref(ref)) for ref in settings.telegram_channels]
    tasks: set[asyncio.Task[str]] = set()

    def schedule(message: Any) -> None:
        # Handlers must return fast or Telethon stops reading updates during big downloads.
        task = asyncio.create_task(ingestor.handle(message))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    @client.on(events.NewMessage(chats=chats))
    async def _on_new_message(event: Any) -> None:
        schedule(event.message)

    if settings.telegram_backfill_messages:
        for chat in chats:
            history = [
                message
                async for message in client.iter_messages(chat, limit=settings.telegram_backfill_messages)
            ]
            for message in reversed(history):
                schedule(message)

    LOGGER.info(
        "Telegram listener started: channels=%d concurrent=%d backfill=%d terabox=%s",
        len(chats),
        settings.telegram_concurrent_downloads,
        settings.telegram_backfill_messages,
        settings.terabox_enabled,
    )
    await client.run_until_disconnected()


def _restrict_session_file(settings: Settings) -> None:
    session_file = Path(f"{settings.telegram_session_path}.session")
    if session_file.exists():
        os.chmod(session_file, 0o600)


def _remove_partial(partial: Path) -> None:
    try:
        partial.unlink(missing_ok=True)
        partial.parent.rmdir()
    except OSError:
        pass
