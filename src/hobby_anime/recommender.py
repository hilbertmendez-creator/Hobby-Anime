from __future__ import annotations

import json
from dataclasses import replace
from difflib import SequenceMatcher
from typing import Iterable

import requests

from hobby_anime.library import normalize_title
from hobby_anime.models import LibraryItem, SeasonalMedia


def mark_library_matches(
    library: Iterable[LibraryItem],
    seasonal_media: Iterable[SeasonalMedia],
) -> list[SeasonalMedia]:
    local_titles = [normalize_title(item.title) for item in library]
    result: list[SeasonalMedia] = []
    for media in seasonal_media:
        candidate_titles = [normalize_title(media.title)]
        candidate_titles.extend(normalize_title(title) for title in media.alternative_titles)
        matched = any(
            _titles_match(local_title, candidate)
            for local_title in local_titles
            for candidate in candidate_titles
        )
        result.append(replace(media, in_library=matched))
    return result


class OllamaRecommender:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: int = 180,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def generate(self, library: list[LibraryItem], seasonal_media: list[SeasonalMedia]) -> str:
        response = self.session.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": build_prompt(library, seasonal_media),
                "stream": False,
                "options": {"temperature": 0.3},
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        content = response.json().get("response", "").strip()
        if not content:
            raise RuntimeError("Ollama returned an empty report")
        return content


def build_prompt(library: list[LibraryItem], seasonal_media: list[SeasonalMedia]) -> str:
    local_payload = [
        {
            "title": item.title,
            "files": item.file_count,
            "latest_episode": item.latest_episode,
        }
        for item in library[:100]
    ]
    season_payload = [
        {
            "title": item.title,
            "alternative_titles": item.alternative_titles,
            "episodes": item.episodes,
            "genres": item.genres,
            "score": item.score,
            "in_library": item.in_library,
            "url": item.url,
        }
        for item in seasonal_media[:50]
    ]
    return (
        "Actúa como curador de una biblioteca personal de anime. Responde en español neutro y en "
        "Markdown. No inventes episodios ni datos. Compara el catálogo local con la temporada actual. "
        "Entrega exactamente estas secciones: Resumen, Posibles episodios faltantes y 3 recomendaciones. "
        "Para faltantes, menciona solo casos sustentados por el total de episodios y el último episodio "
        "local. En cada recomendación explica brevemente por qué encaja y agrega el enlace de AniList.\n\n"
        f"Catálogo local:\n{json.dumps(local_payload, ensure_ascii=False)}\n\n"
        f"Temporada actual:\n{json.dumps(season_payload, ensure_ascii=False)}"
    )


def build_fallback_report(
    library: list[LibraryItem],
    seasonal_media: list[SeasonalMedia],
) -> str:
    missing: list[str] = []
    local_by_title = {normalize_title(item.title): item for item in library}
    for media in seasonal_media:
        if not media.in_library or media.episodes is None:
            continue
        local = _find_local(media, local_by_title)
        if local and local.latest_episode is not None and local.latest_episode < media.episodes:
            missing.append(
                f"- {media.title}: local hasta {local.latest_episode}; AniList registra "
                f"{media.episodes} episodios."
            )

    recommendations = sorted(
        (media for media in seasonal_media if not media.in_library),
        key=lambda media: media.score or 0,
        reverse=True,
    )[:3]
    recommendation_lines = [
        f"{index}. [{media.title}]({media.url}) — puntuación AniList: "
        f"{media.score or 'sin datos'}; géneros: {', '.join(media.genres) or 'sin datos'}."
        for index, media in enumerate(recommendations, 1)
    ]
    return "\n".join(
        [
            "# Reporte mensual de Hobby-Anime",
            "## Resumen",
            f"- Títulos locales detectados: {len(library)}",
            f"- Estrenos de temporada analizados: {len(seasonal_media)}",
            "## Posibles episodios faltantes",
            *(missing or ["- No se detectaron faltantes verificables con los datos disponibles."]),
            "## 3 recomendaciones",
            *(recommendation_lines or ["- No hay suficientes estrenos nuevos para recomendar."]),
        ]
    )


def _titles_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.9


def _find_local(
    media: SeasonalMedia,
    local_by_title: dict[str, LibraryItem],
) -> LibraryItem | None:
    candidate_titles = [media.title, *media.alternative_titles]
    for candidate in candidate_titles:
        normalized = normalize_title(candidate)
        if normalized in local_by_title:
            return local_by_title[normalized]
    for local_title, item in local_by_title.items():
        if any(_titles_match(local_title, normalize_title(candidate)) for candidate in candidate_titles):
            return item
    return None
