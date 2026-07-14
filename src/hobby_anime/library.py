from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from hobby_anime.models import LibraryItem

VIDEO_EXTENSIONS = {
    ".avi",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".webm",
}
EPISODE_PATTERNS = (
    re.compile(r"\bS\d{1,2}E(\d{1,4})\b", re.IGNORECASE),
    re.compile(r"\b(?:EP?|EPISODE)[\s._-]*(\d{1,4})\b", re.IGNORECASE),
    re.compile(r"\s-\s(\d{1,4})(?:v\d+)?(?:\D|$)", re.IGNORECASE),
)


def audit_library(media_path: Path) -> list[LibraryItem]:
    if not media_path.exists():
        raise FileNotFoundError(f"Media directory does not exist: {media_path}")
    if not media_path.is_dir():
        raise NotADirectoryError(f"Media path is not a directory: {media_path}")

    groups: dict[tuple[str, Path], list[Path]] = defaultdict(list)
    for path in media_path.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in VIDEO_EXTENSIONS:
            continue
        relative = path.relative_to(media_path)
        if len(relative.parts) > 1:
            root = media_path / relative.parts[0]
            title = relative.parts[0]
        else:
            root = media_path
            title = _title_from_filename(path.stem)
        groups[(title, root)].append(path)

    result: list[LibraryItem] = []
    for (title, root), files in groups.items():
        episodes = [episode for path in files if (episode := extract_episode(path.stem)) is not None]
        result.append(
            LibraryItem(
                title=title,
                path=root,
                file_count=len(files),
                latest_episode=max(episodes, default=None),
            )
        )
    return sorted(result, key=lambda item: item.title.casefold())


def extract_episode(value: str) -> int | None:
    for pattern in EPISODE_PATTERNS:
        match = pattern.search(value)
        if match:
            return int(match.group(1))
    return None


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", normalized.casefold()).strip()


def _title_from_filename(value: str) -> str:
    value = re.sub(r"^\[[^\]]+\]\s*", "", value)
    value = re.sub(r"\[[^\]]*(?:1080p|720p|2160p|web|bluray)[^\]]*\]", "", value, flags=re.I)
    for pattern in EPISODE_PATTERNS:
        value = pattern.sub("", value)
    return re.sub(r"[\s._-]+$", "", value).strip() or "Unsorted"
