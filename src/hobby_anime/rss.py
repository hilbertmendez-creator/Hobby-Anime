from __future__ import annotations

import calendar
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

import feedparser
import requests

from hobby_anime.models import FeedItem


class RssReader:
    def __init__(self, timeout_seconds: int = 30, session: requests.Session | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def fetch(self, urls: Iterable[str]) -> list[FeedItem]:
        items: list[FeedItem] = []
        for url in urls:
            response = self.session.get(
                url,
                timeout=self.timeout_seconds,
                headers={"User-Agent": "Hobby-Anime/0.1"},
            )
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                raise ValueError(f"Invalid RSS feed at {url}: {parsed.bozo_exception}")
            items.extend(self._to_item(entry) for entry in parsed.entries)
        return items

    @staticmethod
    def _to_item(entry: Any) -> FeedItem:
        title = str(entry.get("title", "")).strip()
        download_url = _download_url(entry)
        if not title or not download_url:
            raise ValueError("RSS entry is missing a title or download URL")

        identity = str(entry.get("id") or entry.get("guid") or f"{title}|{download_url}")
        fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        published_at = _published_at(entry)
        return FeedItem(fingerprint, title, download_url, published_at)


def filter_items(
    items: Iterable[FeedItem],
    *,
    resolution: str = "1080p",
    groups: Iterable[str] = (),
    include_terms: Iterable[str] = (),
    exclude_terms: Iterable[str] = (),
    max_age_hours: int = 72,
    now: datetime | None = None,
) -> list[FeedItem]:
    normalized_groups = tuple(value.casefold() for value in groups)
    required = tuple(value.casefold() for value in include_terms)
    excluded = tuple(value.casefold() for value in exclude_terms)
    resolution = resolution.casefold()
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=max_age_hours)
    matches: list[FeedItem] = []

    for item in items:
        title = item.title.casefold()
        if resolution and resolution not in title:
            continue
        if normalized_groups and not any(group in title for group in normalized_groups):
            continue
        if required and not all(term in title for term in required):
            continue
        if excluded and any(term in title for term in excluded):
            continue
        if item.published_at and item.published_at < cutoff:
            continue
        matches.append(item)
    return matches


def _download_url(entry: Any) -> str:
    candidates: list[str] = []
    link = entry.get("link")
    if link:
        candidates.append(str(link))
    for candidate in entry.get("links", []):
        href = candidate.get("href")
        if href:
            candidates.append(str(href))

    for candidate in candidates:
        if candidate.startswith("magnet:"):
            return candidate
    for candidate in candidates:
        if candidate.endswith(".torrent") or "/download/" in candidate:
            return candidate
    return candidates[0] if candidates else ""


def _published_at(entry: Any) -> datetime | None:
    value = entry.get("published_parsed") or entry.get("updated_parsed")
    if not value:
        return None
    return datetime.fromtimestamp(calendar.timegm(value), tz=UTC)
