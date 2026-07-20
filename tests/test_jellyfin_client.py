from pathlib import Path

import requests

from hobby_anime.jellyfin_client import JellyfinClient, _to_episode, _to_series
from hobby_anime.models import WatchedEpisode, WatchedSeries


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} Client Error for url"
            )

    def json(self) -> object:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._responses = list(responses or [])

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        if self._responses:
            return self._responses.pop(0)
        return FakeResponse({"Items": [], "TotalRecordCount": 0})


def _series_item(
    item_id: str,
    name: str,
    recursive_count: int | None,
    unplayed: int | None,
) -> dict:
    return {
        "Id": item_id,
        "Name": name,
        "RecursiveItemCount": recursive_count,
        "UserData": {"UnplayedItemCount": unplayed},
    }


def _episode_item(item_id: str, name: str, played: bool) -> dict:
    return {"Id": item_id, "Name": name, "UserData": {"Played": played}}


# --- Pure parsers (Group 3, task 6/7) ---


def test_to_series_parses_valid_json_with_recursive_item_count() -> None:
    item = _series_item("s1", "Frieren", recursive_count=28, unplayed=16)

    series = _to_series(item)

    assert series == WatchedSeries(id="s1", name="Frieren", total_episodes=28, watched_episodes=12)


def test_to_series_returns_none_when_recursive_item_count_missing() -> None:
    item = _series_item("s1", "Frieren", recursive_count=None, unplayed=16)

    assert _to_series(item) is None


def test_to_episode_parses_valid_json() -> None:
    item = _episode_item("e1", "Episode 1", played=True)

    episode = _to_episode(item)

    assert episode == WatchedEpisode(id="e1", name="Episode 1", played=True)


# --- Auth header (task 8/9) ---


def test_auth_header_sent_on_every_request_and_never_in_url() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "Items": [_series_item("s1", "Frieren", 28, 16)],
                    "TotalRecordCount": 1,
                }
            )
        ]
    )
    client = JellyfinClient(
        "http://jellyfin:8096",
        api_key="top-secret-key",
        user_id="user-1",
        session=session,
    )

    client.list_watched_series()

    url, kwargs = session.calls[0]
    assert kwargs["headers"]["X-Emby-Token"] == "top-secret-key"
    assert "top-secret-key" not in url
    assert "params" not in kwargs or "top-secret-key" not in str(kwargs.get("params"))


# --- Pagination (task 10/11) ---


def test_list_watched_series_pages_through_all_items() -> None:
    page1 = FakeResponse(
        {
            "Items": [_series_item("s1", "Series 1", 10, 0)],
            "TotalRecordCount": 2,
        }
    )
    page2 = FakeResponse(
        {
            "Items": [_series_item("s2", "Series 2", 12, 12)],
            "TotalRecordCount": 2,
        }
    )
    session = FakeSession([page1, page2])
    client = JellyfinClient(
        "http://jellyfin:8096",
        api_key="key",
        user_id="user-1",
        session=session,
    )
    client.PAGE_SIZE = 1  # force pagination across two pages

    result = client.list_watched_series()

    assert [series.id for series in result] == ["s1", "s2"]
    assert len(session.calls) == 2
    first_params = session.calls[0][1]["params"]
    second_params = session.calls[1][1]["params"]
    assert first_params["StartIndex"] == 0
    assert second_params["StartIndex"] == 1


# --- Empty library (task 12/13) ---


def test_list_watched_series_returns_empty_list_for_empty_library() -> None:
    session = FakeSession([FakeResponse({"Items": [], "TotalRecordCount": 0})])
    client = JellyfinClient(
        "http://jellyfin:8096",
        api_key="key",
        user_id="user-1",
        session=session,
    )

    assert client.list_watched_series() == []


# --- Auth error, no key leak (task 14/15) ---


def test_auth_error_does_not_leak_api_key() -> None:
    session = FakeSession([FakeResponse({}, status_code=401)])
    client = JellyfinClient(
        "http://jellyfin:8096",
        api_key="top-secret-key",
        user_id="user-1",
        session=session,
    )

    try:
        client.list_watched_series()
        raised = False
    except requests.HTTPError as exc:
        raised = True
        assert "top-secret-key" not in str(exc)
        assert "top-secret-key" not in repr(exc)

    assert raised
    for url, _kwargs in session.calls:
        assert "top-secret-key" not in url


# --- Episodes on demand (task 16/17) ---


def test_episodes_returns_played_flags_for_series() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "Items": [
                        _episode_item("e1", "Episode 1", True),
                        _episode_item("e2", "Episode 2", False),
                    ],
                    "TotalRecordCount": 2,
                }
            )
        ]
    )
    client = JellyfinClient(
        "http://jellyfin:8096",
        api_key="key",
        user_id="user-1",
        session=session,
    )

    episodes = client.episodes("s1")

    assert episodes == [
        WatchedEpisode(id="e1", name="Episode 1", played=True),
        WatchedEpisode(id="e2", name="Episode 2", played=False),
    ]
    url, kwargs = session.calls[0]
    assert kwargs["params"]["ParentId"] == "s1"
    assert kwargs["params"]["IncludeItemTypes"] == "Episode"


# --- Fallback when RecursiveItemCount is absent ---


def test_list_watched_series_falls_back_to_episode_fetch_when_recursive_count_missing() -> None:
    series_page = FakeResponse(
        {
            "Items": [_series_item("s1", "Frieren", recursive_count=None, unplayed=None)],
            "TotalRecordCount": 1,
        }
    )
    episodes_page = FakeResponse(
        {
            "Items": [
                _episode_item("e1", "Episode 1", True),
                _episode_item("e2", "Episode 2", False),
                _episode_item("e3", "Episode 3", True),
            ],
            "TotalRecordCount": 3,
        }
    )
    session = FakeSession([series_page, episodes_page])
    client = JellyfinClient(
        "http://jellyfin:8096",
        api_key="key",
        user_id="user-1",
        session=session,
    )

    result = client.list_watched_series()

    assert result == [
        WatchedSeries(id="s1", name="Frieren", total_episodes=3, watched_episodes=2)
    ]


# --- series_path (Item B, PR1, tasks 1.1-1.6) ---


def test_series_path_returns_path_from_series_fields() -> None:
    session = FakeSession([FakeResponse({"Path": "/data/media/anime/Frieren"})])
    client = JellyfinClient(
        "http://jellyfin:8096",
        api_key="key",
        user_id="user-1",
        session=session,
    )

    result = client.series_path("s1")

    assert result == Path("/data/media/anime/Frieren")
    url, kwargs = session.calls[0]
    assert url == "http://jellyfin:8096/Users/user-1/Items/s1"
    assert kwargs["params"]["Fields"] == "Path"


def test_series_path_falls_back_to_media_sources_common_parent() -> None:
    series_response = FakeResponse({})  # no "Path" key
    episodes_response = FakeResponse(
        {
            "Items": [
                {
                    "Id": "e1",
                    "MediaSources": [
                        {"Path": "/data/media/anime/Frieren/S01/e1.mkv"}
                    ],
                },
                {
                    "Id": "e2",
                    "MediaSources": [
                        {"Path": "/data/media/anime/Frieren/S01/e2.mkv"}
                    ],
                },
            ],
            "TotalRecordCount": 2,
        }
    )
    session = FakeSession([series_response, episodes_response])
    client = JellyfinClient(
        "http://jellyfin:8096",
        api_key="key",
        user_id="user-1",
        session=session,
    )

    result = client.series_path("s1")

    assert result == Path("/data/media/anime/Frieren/S01")


def test_series_path_returns_none_when_path_and_media_sources_absent() -> None:
    series_response = FakeResponse({})
    episodes_response = FakeResponse({"Items": [], "TotalRecordCount": 0})
    session = FakeSession([series_response, episodes_response])
    client = JellyfinClient(
        "http://jellyfin:8096",
        api_key="key",
        user_id="user-1",
        session=session,
    )

    assert client.series_path("s1") is None
