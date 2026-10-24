from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.manual_review import approve_rejection
from hobby_anime.models import MediaInspection, TorrentDownload
from hobby_anime.telegram_listener import TelegramIngestor, message_file_name, parse_channel_ref
from hobby_anime.telegram_source import (
    candidate_rejection,
    message_fingerprint,
    safe_filename,
    verify_download,
)

MB = 1024**2


class FakeInspector:
    def __init__(self, accepted: bool) -> None:
        self.accepted = accepted
        self.calls: list[Path] = []

    def inspect(self, content_path: Path) -> MediaInspection:
        self.calls.append(content_path)
        return MediaInspection(
            accepted=self.accepted,
            audio_languages=("spa",) if self.accepted else ("jpn",),
            reason="ok" if self.accepted else "No Spanish audio or full subtitle track was detected",
        )


@pytest.fixture
def tg_settings(settings: Settings, tmp_path: Path) -> Settings:
    return replace(
        settings,
        telegram_source_enabled=True,
        telegram_api_id=12345,
        telegram_api_hash="hash",
        telegram_channels=("@canal",),
        telegram_quarantine_path=tmp_path / "torrents" / "telegram" / "quarantine",
        telegram_verified_path=tmp_path / "torrents" / "verified" / "telegram",
        sonarr_verified_root=tmp_path / "torrents" / "verified",
        sonarr_enabled=True,
        minimum_free_space_gb=0,
        telegram_min_file_mb=1,
    )


@pytest.fixture
def database(tg_settings: Settings) -> TrackingDatabase:
    db = TrackingDatabase(tg_settings.database_path)
    db.initialize()
    return db


def _message(chat_id: int, message_id: int, name: str | None, size: int, caption: str = "", ext: str = ".mkv"):
    return SimpleNamespace(
        chat_id=chat_id,
        id=message_id,
        message=caption,
        file=SimpleNamespace(name=name, size=size, ext=ext),
    )


def _write_file(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)


def test_fingerprint_is_stable_and_positive() -> None:
    assert message_fingerprint(-1001234, 77) == "tg-1001234-77"


def test_safe_filename_strips_paths_and_unsafe_characters() -> None:
    assert safe_filename("../../etc/pass:wd?.mkv", "x.mkv") == "pass wd .mkv"
    assert safe_filename("", "fallback.mkv") == "fallback.mkv"
    assert safe_filename("..", "fallback.mkv") == "fallback.mkv"
    long_name = "a" * 300 + ".mkv"
    result = safe_filename(long_name, "x.mkv")
    assert len(result) <= 180 and result.endswith(".mkv")


@pytest.mark.parametrize(
    ("name", "size", "expected"),
    [
        ("Show - 01 [1080p].mkv", 500 * MB, None),
        ("poster.jpg", 500 * MB, "not a supported video file"),
        ("Show - 01.mkv", None, "unknown file size"),
        ("Show - 01.mkv", 100, "smaller than"),
        ("Show - 01.mkv", 5 * 1024**3, "larger than"),
        ("Show - 01 CAM.mkv", 500 * MB, "excluded term"),
        ("Show - 01 RAW.mkv", 500 * MB, "Spanish policy negative term"),
    ],
)
def test_candidate_rejection(tg_settings: Settings, name: str, size: int | None, expected: str | None) -> None:
    settings = replace(tg_settings, telegram_exclude_terms=("cam",))
    reason = candidate_rejection(name, size, settings)
    if expected is None:
        assert reason is None
    else:
        assert reason is not None and expected in reason


def test_candidate_rejection_requires_all_include_terms(tg_settings: Settings) -> None:
    settings = replace(tg_settings, telegram_include_terms=("1080p", "latino"))
    assert "latino" in candidate_rejection("Show - 01 [1080p].mkv", 500 * MB, settings)
    assert candidate_rejection("Show - 01 [1080p] Latino.mkv", 500 * MB, settings) is None


def test_verified_file_is_promoted_and_queued(tg_settings: Settings, database: TrackingDatabase) -> None:
    fingerprint = "tg-1-10"
    source = tg_settings.telegram_quarantine_path / fingerprint / "Show - 01.mkv"
    _write_file(source, 10)
    download = TorrentDownload(fingerprint, source.name, source)

    status = verify_download(download, tg_settings, inspector=FakeInspector(True), database=database)

    target = tg_settings.telegram_verified_path / fingerprint / "Show - 01.mkv"
    assert status == "verified"
    assert target.is_file() and not source.exists()
    assert database.verification_status(fingerprint) == "verified"
    assert database.import_status(fingerprint) == "pending"
    assert database.pending_imports()[0].content_path == target


def test_rejected_file_stays_in_quarantine_and_can_be_approved(
    tg_settings: Settings, database: TrackingDatabase
) -> None:
    fingerprint = "tg-1-11"
    source = tg_settings.telegram_quarantine_path / fingerprint / "Show - 02.mkv"
    _write_file(source, 10)
    download = TorrentDownload(fingerprint, source.name, source)

    status = verify_download(download, tg_settings, inspector=FakeInspector(False), database=database)
    assert status == "rejected"
    assert source.is_file()
    assert database.import_status(fingerprint) is None

    # No qBittorrent password needed for Telegram approvals.
    approve_rejection(replace(tg_settings, qbt_password=""), fingerprint, database=database)
    assert (tg_settings.telegram_verified_path / fingerprint / "Show - 02.mkv").is_file()
    assert database.verification_status(fingerprint) == "verified"
    assert database.import_status(fingerprint) == "pending"


def test_file_outside_quarantine_is_an_error(tg_settings: Settings, database: TrackingDatabase, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere" / "Show.mkv"
    _write_file(outside, 10)
    download = TorrentDownload("tg-1-12", outside.name, outside)
    assert verify_download(download, tg_settings, inspector=FakeInspector(True), database=database) == "error"
    assert outside.is_file()


def test_ingestor_downloads_verifies_and_skips_duplicates(
    tg_settings: Settings, database: TrackingDatabase
) -> None:
    downloads: list[Path] = []

    async def fake_download(message, path: Path) -> None:
        downloads.append(path)
        _write_file(path, message.file.size)

    inspector = FakeInspector(True)
    ingestor = TelegramIngestor(tg_settings, download=fake_download, database=database, inspector=inspector)
    message = _message(-100500, 7, "Show - 03 [1080p].mkv", 2 * MB)

    async def run() -> tuple[str, str]:
        return await ingestor.handle(message), await ingestor.handle(message)

    first, second = asyncio.run(run())
    assert first == "verified"
    assert second == "duplicate"
    assert len(downloads) == 1 and downloads[0].name.endswith(".part")
    assert (tg_settings.telegram_verified_path / "tg-100500-7" / "Show - 03 [1080p].mkv").is_file()


def test_ingestor_filters_without_downloading(tg_settings: Settings, database: TrackingDatabase) -> None:
    async def fail_download(message, path: Path) -> None:
        raise AssertionError("should not download")

    ingestor = TelegramIngestor(
        tg_settings, download=fail_download, database=database, inspector=FakeInspector(True)
    )
    assert asyncio.run(ingestor.handle(_message(-1, 1, "cover.jpg", 2 * MB))) == "filtered"
    assert asyncio.run(ingestor.handle(SimpleNamespace(chat_id=-1, id=2, file=None))) == "no-file"


def test_ingestor_records_error_and_cleans_partial_download(
    tg_settings: Settings, database: TrackingDatabase
) -> None:
    async def broken_download(message, path: Path) -> None:
        _write_file(path, 10)
        raise ConnectionError("lost connection")

    ingestor = TelegramIngestor(
        tg_settings, download=broken_download, database=database, inspector=FakeInspector(True)
    )
    message = _message(-1, 3, "Show - 04.mkv", 2 * MB)
    assert asyncio.run(ingestor.handle(message)) == "error"
    assert database.verification_status("tg-1-3") == "error"
    assert not (tg_settings.telegram_quarantine_path / "tg-1-3").exists()

    # An errored message is retried when it shows up again (for example on backfill).
    async def good_download(message, path: Path) -> None:
        _write_file(path, message.file.size)

    ingestor.download = good_download
    assert asyncio.run(ingestor.handle(message)) == "verified"


def test_message_file_name_falls_back_to_caption_then_id() -> None:
    with_caption = _message(-1, 5, None, MB, caption="Mi Serie - 05 Latino\nmás texto", ext=".mp4")
    assert message_file_name(with_caption, "tg-1-5") == "Mi Serie - 05 Latino.mp4"
    bare = _message(-1, 6, None, MB, ext=".mp4")
    assert message_file_name(bare, "tg-1-6") == "tg-1-6.mp4"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("@canal", "canal"),
        ("canal", "canal"),
        ("https://t.me/canal/", "canal"),
        ("-1001234567890", -1001234567890),
    ],
)
def test_parse_channel_ref(value: str, expected: str | int) -> None:
    assert parse_channel_ref(value) == expected


def test_validate_telegram(tg_settings: Settings) -> None:
    tg_settings.validate_telegram()
    with pytest.raises(ValueError, match="TELEGRAM_API_ID"):
        replace(tg_settings, telegram_api_id=0).validate_telegram()
    with pytest.raises(ValueError, match="SONARR_VERIFIED_ROOT"):
        replace(tg_settings, telegram_verified_path=Path("/elsewhere")).validate_telegram()
    with pytest.raises(ValueError, match="must not overlap"):
        replace(
            tg_settings, telegram_verified_path=tg_settings.telegram_quarantine_path / "ok"
        ).validate_telegram()
    replace(tg_settings, telegram_channels=(), telegram_source_enabled=False).validate_telegram(for_login=True)


def test_settings_from_env_reads_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_SOURCE_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_API_ID", "999")
    monkeypatch.setenv("TELEGRAM_CHANNELS", "@uno, -100200")
    monkeypatch.setenv("TELEGRAM_MAX_FILE_GB", "2")
    settings = Settings.from_env()
    assert settings.telegram_source_enabled is True
    assert settings.telegram_api_id == 999
    assert settings.telegram_channels == ("@uno", "-100200")
    assert settings.telegram_max_file_gb == 2
