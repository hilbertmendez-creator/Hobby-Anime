from __future__ import annotations

from typing import Any

import requests

from hobby_anime.models import AniListMatch

SEARCH_QUERY = """
query ($search: String) {
  Page(page: 1, perPage: 10) {
    media(search: $search, type: ANIME, isAdult: false) {
      id
      title { romaji english }
      startDate { year }
    }
  }
}
"""

GET_LIST_ENTRY_QUERY = """
query ($mediaId: Int) {
  Media(id: $mediaId) {
    mediaListEntry {
      status
      progress
    }
  }
}
"""

SAVE_MUTATION = """
mutation ($mediaId: Int, $status: MediaListStatus, $progress: Int) {
  SaveMediaListEntry(mediaId: $mediaId, status: $status, progress: $progress) {
    id
    status
    progress
  }
}
"""


def _to_match(item: dict[str, Any]) -> AniListMatch:
    """Parse a Media search result item into an AniListMatch."""
    titles = item.get("title") or {}
    year = (item.get("startDate") or {}).get("year")
    return AniListMatch(
        media_id=int(item["id"]),
        title=titles.get("romaji") or titles.get("english") or "Untitled",
        year=year,
    )


def _to_entry(entry: dict[str, Any] | None) -> tuple[str, int] | None:
    """Parse a MediaListEntry-shaped dict into (status, progress), or None when absent."""
    if entry is None:
        return None
    return (entry["status"], entry["progress"])


class AniListWriteClient:
    """Authenticated write-capable AniList GraphQL client.

    Sends the access token exclusively via `Authorization: Bearer` header.
    The token is never placed in the URL, query params, request body, or
    surfaced in any exception raised by this class. This class is fully
    separate from the anonymous, read-only `AniListClient` and never
    modifies its behavior.
    """

    def __init__(
        self,
        access_token: str,
        url: str = "https://graphql.anilist.co",
        timeout_seconds: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self._access_token = access_token

    def search_media(self, title: str) -> list[AniListMatch]:
        payload = self._post(SEARCH_QUERY, {"search": title})
        media_list = payload["data"]["Page"]["media"]
        return [_to_match(item) for item in media_list]

    def get_list_entry(self, media_id: int) -> tuple[str, int] | None:
        payload = self._post(GET_LIST_ENTRY_QUERY, {"mediaId": media_id})
        media = payload["data"]["Media"]
        entry = media.get("mediaListEntry") if media else None
        return _to_entry(entry)

    def save_media_list_entry(
        self, media_id: int, status: str, progress: int
    ) -> tuple[str, int] | None:
        payload = self._post(
            SAVE_MUTATION,
            {"mediaId": media_id, "status": status, "progress": progress},
        )
        entry = payload["data"]["SaveMediaListEntry"]
        return _to_entry(entry)

    def _post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            self.url,
            json={"query": query, "variables": variables},
            timeout=self.timeout_seconds,
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "User-Agent": "Hobby-Anime/0.1",
            },
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        if payload.get("errors"):
            raise RuntimeError(f"AniList GraphQL error: {payload['errors']}")
        return payload
