from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class FeedItem:
    fingerprint: str
    title: str
    download_url: str
    published_at: datetime | None = None
    description: str = ""
    categories: tuple[str, ...] = ()


@dataclass(frozen=True)
class TorrentDownload:
    torrent_hash: str
    name: str
    content_path: Path


@dataclass(frozen=True)
class RejectedDownload:
    torrent_hash: str
    name: str
    reason: str
    content_path: Path
    updated_at: str


@dataclass(frozen=True)
class MediaInspection:
    accepted: bool
    audio_languages: tuple[str, ...] = ()
    subtitle_languages: tuple[str, ...] = ()
    inspected_files: tuple[Path, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class LibraryItem:
    title: str
    path: Path
    file_count: int
    latest_episode: int | None = None


@dataclass(frozen=True)
class SeasonalMedia:
    anilist_id: int
    title: str
    alternative_titles: tuple[str, ...] = ()
    episodes: int | None = None
    genres: tuple[str, ...] = ()
    score: int | None = None
    description: str = ""
    url: str = ""
    in_library: bool = False


@dataclass
class DailyRunResult:
    discovered: int = 0
    matched: int = 0
    added: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class VerificationRunResult:
    discovered: int = 0
    verified: int = 0
    rejected: int = 0
    imported: int = 0
    import_failed: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ImportRunResult:
    discovered: int = 0
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WatchedSeries:
    id: str
    name: str
    total_episodes: int
    watched_episodes: int


@dataclass(frozen=True)
class WatchedEpisode:
    id: str
    name: str
    played: bool


@dataclass(frozen=True)
class CleanupCandidate:
    series_id: str
    series_name: str
    path: Path
    status: str  # "deletable" | "skipped" | "error"
    reason: str = ""
    freed_bytes: int = 0
    hardlinked: bool = False


@dataclass(frozen=True)
class CleanupReport:
    executed: bool
    deletable: int
    skipped: int
    errors: int
    freed_bytes: int
    items: tuple[CleanupCandidate, ...] = ()
