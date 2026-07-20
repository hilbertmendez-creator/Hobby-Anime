from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests

from hobby_anime.models import WatchedEpisode, WatchedSeries


def _to_series(item: dict[str, Any]) -> WatchedSeries | None:
    """Parse a Jellyfin Series item into a WatchedSeries summary.

    Returns None when `RecursiveItemCount` is not present on the item, so the
    caller can fall back to a per-series episode fetch.
    """
    recursive_count = item.get("RecursiveItemCount")
    if recursive_count is None:
        return None
    user_data = item.get("UserData") or {}
    unplayed = user_data.get("UnplayedItemCount") or 0
    return WatchedSeries(
        id=item["Id"],
        name=item.get("Name", ""),
        total_episodes=recursive_count,
        watched_episodes=recursive_count - unplayed,
    )


def _to_episode(item: dict[str, Any]) -> WatchedEpisode:
    """Parse a Jellyfin Episode item into a WatchedEpisode."""
    user_data = item.get("UserData") or {}
    return WatchedEpisode(
        id=item["Id"],
        name=item.get("Name", ""),
        played=bool(user_data.get("Played", False)),
    )


class JellyfinClient:
    """Read-only client for Jellyfin watched/played status.

    Authenticates every request via the `X-Emby-Token` header only. The API
    key is never sent as a query parameter, logged, or included in error
    messages.
    """

    PAGE_SIZE = 200

    def __init__(
        self,
        base_url: str,
        api_key: str,
        user_id: str,
        timeout_seconds: int = 30,
        library_id: str = "",
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.user_id = user_id
        self.timeout_seconds = timeout_seconds
        self.library_id = library_id
        self.session = session or requests.Session()

    def list_watched_series(self) -> list[WatchedSeries]:
        series_list: list[WatchedSeries] = []
        start_index = 0
        while True:
            params: dict[str, Any] = {
                "IncludeItemTypes": "Series",
                "Recursive": "true",
                "Fields": "UserData",
                "StartIndex": start_index,
                "Limit": self.PAGE_SIZE,
            }
            if self.library_id:
                params["ParentId"] = self.library_id
            payload = self._get(f"/Users/{self.user_id}/Items", params)
            items = payload.get("Items", [])
            for item in items:
                series = _to_series(item)
                if series is None:
                    episodes = self.episodes(item["Id"])
                    series = WatchedSeries(
                        id=item["Id"],
                        name=item.get("Name", ""),
                        total_episodes=len(episodes),
                        watched_episodes=sum(1 for episode in episodes if episode.played),
                    )
                series_list.append(series)
            start_index += len(items)
            total = payload.get("TotalRecordCount", start_index)
            if start_index >= total or not items:
                break
        return series_list

    def episodes(self, series_id: str) -> list[WatchedEpisode]:
        episodes: list[WatchedEpisode] = []
        start_index = 0
        while True:
            params: dict[str, Any] = {
                "ParentId": series_id,
                "IncludeItemTypes": "Episode",
                "Recursive": "true",
                "Fields": "UserData",
                "StartIndex": start_index,
                "Limit": self.PAGE_SIZE,
            }
            payload = self._get(f"/Users/{self.user_id}/Items", params)
            items = payload.get("Items", [])
            episodes.extend(_to_episode(item) for item in items)
            start_index += len(items)
            total = payload.get("TotalRecordCount", start_index)
            if start_index >= total or not items:
                break
        return episodes

    def series_path(self, series_id: str) -> Path | None:
        """Resolve the on-disk folder for a series (read-only, no mutation).

        Fetches the Series item with `Fields=Path` and returns its `Path`
        when present. Falls back to the common parent directory of the
        series' episode `MediaSources[].Path` values when the Series item
        has no `Path`. Returns None when neither source yields a path.
        """
        payload = self._get(
            f"/Users/{self.user_id}/Items/{series_id}",
            {"Fields": "Path"},
        )
        raw_path = payload.get("Path")
        if raw_path:
            return Path(raw_path)
        return self._series_path_from_media_sources(series_id)

    def _series_path_from_media_sources(self, series_id: str) -> Path | None:
        parent_dirs: list[str] = []
        start_index = 0
        while True:
            params: dict[str, Any] = {
                "ParentId": series_id,
                "IncludeItemTypes": "Episode",
                "Recursive": "true",
                "Fields": "MediaSources",
                "StartIndex": start_index,
                "Limit": self.PAGE_SIZE,
            }
            payload = self._get(f"/Users/{self.user_id}/Items", params)
            items = payload.get("Items", [])
            for item in items:
                for source in item.get("MediaSources") or []:
                    source_path = source.get("Path")
                    if source_path:
                        parent_dirs.append(str(Path(source_path).parent))
            start_index += len(items)
            total = payload.get("TotalRecordCount", start_index)
            if start_index >= total or not items:
                break
        if not parent_dirs:
            return None
        return Path(os.path.commonpath(parent_dirs))

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        response = self.session.get(
            f"{self.base_url}{path}",
            headers={"Accept": "application/json", "X-Emby-Token": self.api_key},
            params=params,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
