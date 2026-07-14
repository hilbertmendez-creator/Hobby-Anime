from __future__ import annotations

import html
import re
from datetime import date
from typing import Any

import requests

from hobby_anime.models import SeasonalMedia

QUERY = """
query ($season: MediaSeason!, $seasonYear: Int!, $page: Int!) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    media(
      season: $season
      seasonYear: $seasonYear
      type: ANIME
      sort: POPULARITY_DESC
      isAdult: false
    ) {
      id
      title { romaji english native }
      episodes
      genres
      averageScore
      description(asHtml: false)
      siteUrl
    }
  }
}
"""


class AniListClient:
    def __init__(
        self,
        url: str = "https://graphql.anilist.co",
        timeout_seconds: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def current_season(self, today: date | None = None) -> list[SeasonalMedia]:
        today = today or date.today()
        season = _season_for_month(today.month)
        result: list[SeasonalMedia] = []
        page = 1

        while True:
            response = self.session.post(
                self.url,
                json={"query": QUERY, "variables": {"season": season, "seasonYear": today.year, "page": page}},
                timeout=self.timeout_seconds,
                headers={"User-Agent": "Hobby-Anime/0.1"},
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            if payload.get("errors"):
                raise RuntimeError(f"AniList error: {payload['errors']}")
            page_data = payload["data"]["Page"]
            result.extend(_to_media(item) for item in page_data["media"])
            if not page_data["pageInfo"]["hasNextPage"]:
                return result
            page += 1


def _season_for_month(month: int) -> str:
    if month <= 3:
        return "WINTER"
    if month <= 6:
        return "SPRING"
    if month <= 9:
        return "SUMMER"
    return "FALL"


def _to_media(item: dict[str, Any]) -> SeasonalMedia:
    titles = item["title"]
    alternatives = tuple(
        value for key in ("english", "native") if (value := titles.get(key)) and value != titles.get("romaji")
    )
    description = html.unescape(re.sub(r"<[^>]+>", "", item.get("description") or ""))
    return SeasonalMedia(
        anilist_id=int(item["id"]),
        title=titles.get("romaji") or titles.get("english") or "Untitled",
        alternative_titles=alternatives,
        episodes=item.get("episodes"),
        genres=tuple(item.get("genres") or ()),
        score=item.get("averageScore"),
        description=description,
        url=item.get("siteUrl") or "",
    )
