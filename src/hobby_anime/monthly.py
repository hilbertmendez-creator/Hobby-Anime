from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hobby_anime.anilist import AniListClient
from hobby_anime.config import Settings
from hobby_anime.library import audit_library
from hobby_anime.models import LibraryItem
from hobby_anime.notifications import Notifier
from hobby_anime.recommender import (
    OllamaRecommender,
    build_fallback_report,
    mark_library_matches,
)
from hobby_anime.sonarr_client import SonarrClient

LOGGER = logging.getLogger(__name__)


def run_monthly(
    settings: Settings,
    *,
    anilist_client: AniListClient | None = None,
    notifier: Notifier | None = None,
    recommender: OllamaRecommender | None = None,
    sonarr_client: SonarrClient | None = None,
) -> str:
    library = audit_library(settings.media_path)
    upcoming: list[dict[str, object]] = []
    if settings.sonarr_enabled:
        sonarr_client = sonarr_client or SonarrClient(
            settings.sonarr_url,
            settings.sonarr_api_key,
            settings.request_timeout_seconds,
        )
        try:
            library = _merge_sonarr_library(library, sonarr_client.series())
            now = datetime.now(UTC)
            upcoming = sonarr_client.calendar(now, now + timedelta(days=30))
        except Exception:
            LOGGER.exception("Sonarr query failed; continuing without Sonarr data")
    anilist_client = anilist_client or AniListClient(
        settings.anilist_url,
        settings.request_timeout_seconds,
    )
    try:
        current_season = anilist_client.current_season()
    except Exception:
        LOGGER.exception("AniList query failed; continuing without seasonal data")
        current_season = []
    seasonal_media = mark_library_matches(library, current_season)

    report: str
    if settings.ollama_enabled:
        recommender = recommender or OllamaRecommender(
            settings.ollama_url,
            settings.ollama_model,
        )
        try:
            report = recommender.generate(library, seasonal_media)
        except Exception:
            LOGGER.exception("Ollama failed; using deterministic report")
            report = build_fallback_report(library, seasonal_media)
    else:
        report = build_fallback_report(library, seasonal_media)
    report = _append_calendar(report, upcoming)

    notifier = notifier or Notifier(
        settings.webhook_url,
        settings.telegram_bot_token,
        settings.telegram_chat_id,
        settings.request_timeout_seconds,
    )
    destinations = notifier.send(report)
    LOGGER.info(
        "Monthly run completed: local=%d seasonal=%d notifications=%s",
        len(library),
        len(seasonal_media),
        ",".join(destinations) or "logs",
    )
    return report


def _merge_sonarr_library(
    library: list[LibraryItem],
    series: list[dict[str, object]],
) -> list[LibraryItem]:
    by_path = {item.path: item for item in library}
    for item in series:
        statistics = item.get("statistics") or {}
        if not isinstance(statistics, dict):
            continue
        file_count = int(statistics.get("episodeFileCount") or 0)
        raw_path = str(item.get("path") or "").strip()
        path = Path(raw_path)
        title = str(item.get("title") or "").strip()
        if file_count and title and raw_path and path not in by_path:
            by_path[path] = LibraryItem(title, path, file_count)
    return sorted(by_path.values(), key=lambda item: item.title.casefold())


def _append_calendar(report: str, upcoming: list[dict[str, object]]) -> str:
    if not upcoming:
        return report
    lines = ["", "## Próximos episodios (Sonarr)"]
    for episode in upcoming[:10]:
        series = episode.get("series") or {}
        series_title = (
            str(series.get("title", ""))
            if isinstance(series, dict)
            else ""
        )
        title = str(episode.get("title") or "Episodio")
        air_date = str(episode.get("airDateUtc") or "fecha desconocida")
        lines.append(f"- {series_title}: {title} — {air_date}")
    return f"{report.rstrip()}\n" + "\n".join(lines)
