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
