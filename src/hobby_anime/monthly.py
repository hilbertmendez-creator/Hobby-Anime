from __future__ import annotations

import logging

from hobby_anime.anilist import AniListClient
from hobby_anime.config import Settings
from hobby_anime.library import audit_library
from hobby_anime.notifications import Notifier
from hobby_anime.recommender import (
    OllamaRecommender,
    build_fallback_report,
    mark_library_matches,
)

LOGGER = logging.getLogger(__name__)


def run_monthly(
    settings: Settings,
    *,
    anilist_client: AniListClient | None = None,
    notifier: Notifier | None = None,
    recommender: OllamaRecommender | None = None,
) -> str:
    library = audit_library(settings.media_path)
    anilist_client = anilist_client or AniListClient(
        settings.anilist_url,
        settings.request_timeout_seconds,
    )
    seasonal_media = mark_library_matches(library, anilist_client.current_season())

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
