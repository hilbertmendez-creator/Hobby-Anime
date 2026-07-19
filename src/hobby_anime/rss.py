from __future__ import annotations

import calendar
import hashlib
import html
import logging
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable
from urllib.parse import parse_qs, urlsplit

import feedparser
import requests

from hobby_anime.models import FeedItem

LOGGER = logging.getLogger(__name__)

_ALLOWED_URL_SCHEMES = {"http", "https"}


class RssReader:
    def __init__(self, timeout_seconds: int = 30, session: requests.Session | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def fetch(self, urls: Iterable[str]) -> list[FeedItem]:
        items: list[FeedItem] = []
        for url in urls:
            try:
                response = self.session.get(
                    url,
                    timeout=self.timeout_seconds,
                    headers={"User-Agent": "Hobby-Anime/0.1"},
                )
                response.raise_for_status()
                parsed = feedparser.parse(response.content)
                if parsed.bozo and not parsed.entries:
                    raise ValueError(f"Invalid RSS feed at {url}: {parsed.bozo_exception}")
            except Exception as exc:
                LOGGER.warning("Skipping RSS feed %s: %s", url, exc)
                continue

            for entry in parsed.entries:
                try:
                    items.append(self._to_item(entry))
                except ValueError as exc:
                    LOGGER.warning("Skipping RSS entry from %s: %s", url, exc)
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
        description = _plain_text(str(entry.get("summary") or entry.get("description") or ""))
        categories = tuple(
            str(tag.get("term", "")).strip()
            for tag in entry.get("tags", [])
            if tag.get("term")
        )
        return FeedItem(
            fingerprint,
            title,
            download_url,
            published_at,
            description,
            categories,
        )


def filter_items(
    items: Iterable[FeedItem],
    *,
    resolution: str = "1080p",
    groups: Iterable[str] = (),
    include_terms: Iterable[str] = (),
    exclude_terms: Iterable[str] = (),
    spanish_only: bool = False,
    spanish_language_terms: Iterable[str] = (),
    spanish_negative_terms: Iterable[str] = (),
    spanish_trusted_groups: Iterable[str] = (),
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
        if spanish_only and not matches_spanish_policy(
            item,
            language_terms=spanish_language_terms,
            negative_terms=spanish_negative_terms,
            trusted_groups=spanish_trusted_groups,
        ):
            continue
        if item.published_at and item.published_at < cutoff:
            continue
        matches.append(item)
    return matches


def matches_spanish_policy(
    item: FeedItem,
    *,
    language_terms: Iterable[str],
    negative_terms: Iterable[str] = (),
    trusted_groups: Iterable[str] = (),
) -> bool:
    metadata = _normalized_words(
        " ".join(
            (
                item.title,
                " ".join(item.categories),
                _magnet_display_name(item.download_url),
            )
        )
    )
    release_group = _release_group(item.title)
    if any(_contains_term(metadata, term) for term in negative_terms):
        return False
    if any(_contains_term(metadata, term) for term in language_terms):
        return True
    return any(_contains_term(release_group, group) for group in trusted_groups)


def _download_url(entry: Any) -> str:
    candidates: list[str] = []
    link = entry.get("link")
    if link:
        candidates.append(str(link))
    for candidate in entry.get("links", []):
        href = candidate.get("href")
        if href:
            candidates.append(str(href))

    allowed = [candidate for candidate in candidates if _has_allowed_scheme(candidate)]
    if candidates and not allowed:
        raise ValueError(
            f"RSS entry download URL uses a disallowed scheme: {candidates[0]!r}"
        )

    for candidate in allowed:
        if candidate.startswith("magnet:"):
            return candidate
    for candidate in allowed:
        if candidate.endswith(".torrent") or "/download/" in candidate:
            return candidate
    return allowed[0] if allowed else ""


def _has_allowed_scheme(url: str) -> bool:
    if url.startswith("magnet:"):
        return True
    return urlsplit(url).scheme.lower() in _ALLOWED_URL_SCHEMES


def _published_at(entry: Any) -> datetime | None:
    value = entry.get("published_parsed") or entry.get("updated_parsed")
    if not value:
        return None
    return datetime.fromtimestamp(calendar.timegm(value), tz=UTC)


def _normalized_words(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def _contains_term(normalized_text: str, term: str) -> bool:
    normalized_term = _normalized_words(term)
    if not normalized_term:
        return False
    return f" {normalized_term} " in f" {normalized_text} "


def _magnet_display_name(download_url: str) -> str:
    if not download_url.startswith("magnet:"):
        return ""
    return parse_qs(urlsplit(download_url).query).get("dn", [""])[0]


def _plain_text(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", value))


def _release_group(title: str) -> str:
    match = re.match(r"^\s*\[([^\]]+)\]", title)
    return _normalized_words(match.group(1)) if match else ""
