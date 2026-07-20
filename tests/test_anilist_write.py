import hashlib
from pathlib import Path

import requests

from hobby_anime.anilist_write import AniListWriteClient, _to_entry, _to_match
from hobby_anime.models import AniListMatch

DUMMY_TOKEN = "top-secret-oauth-token"  # noqa: S105 (test fixture value, never real)


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error for url")

    def json(self) -> object:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._responses = list(responses or [])

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        if self._responses:
            return self._responses.pop(0)
        return FakeResponse({"data": {}})


# --- Auth header, no-leak (task 2.1/2.2) ---


def test_bearer_header_sent_and_token_never_in_url_or_body() -> None:
    session = FakeSession([FakeResponse({"data": {"Page": {"media": []}}})])
    client = AniListWriteClient(access_token=DUMMY_TOKEN, session=session)

    client.search_media("Frieren")

    url, kwargs = session.calls[0]
    assert kwargs["headers"]["Authorization"] == f"Bearer {DUMMY_TOKEN}"
    assert DUMMY_TOKEN not in url
    assert DUMMY_TOKEN not in str(kwargs.get("json"))
    assert DUMMY_TOKEN not in str(kwargs.get("params", {}))


def test_error_from_http_failure_never_leaks_token() -> None:
    session = FakeSession([FakeResponse({}, status_code=401)])
    client = AniListWriteClient(access_token=DUMMY_TOKEN, session=session)

    raised = False
    try:
        client.search_media("Frieren")
    except requests.HTTPError as exc:
        raised = True
        assert DUMMY_TOKEN not in str(exc)
        assert DUMMY_TOKEN not in repr(exc)

    assert raised
    for url, _kwargs in session.calls:
        assert DUMMY_TOKEN not in url


def test_error_from_graphql_errors_array_never_leaks_token() -> None:
    session = FakeSession(
        [FakeResponse({"errors": [{"message": "Invalid token"}]})]
    )
    client = AniListWriteClient(access_token=DUMMY_TOKEN, session=session)

    raised = False
    try:
        client.search_media("Frieren")
    except RuntimeError as exc:
        raised = True
        assert DUMMY_TOKEN not in str(exc)

    assert raised


def test_403_and_429_status_codes_raise_http_error_without_leaking_token() -> None:
    for status_code in (403, 429):
        session = FakeSession([FakeResponse({}, status_code=status_code)])
        client = AniListWriteClient(access_token=DUMMY_TOKEN, session=session)

        raised = False
        try:
            client.get_list_entry(123)
        except requests.HTTPError as exc:
            raised = True
            assert DUMMY_TOKEN not in str(exc)

        assert raised


# --- Pure parsers (task 2.3/2.4) ---


def test_to_match_parses_id_title_and_year() -> None:
    item = {
        "id": 123,
        "title": {"romaji": "Frieren", "english": "Frieren: Beyond Journey's End"},
        "startDate": {"year": 2023},
    }

    match = _to_match(item)

    assert match == AniListMatch(media_id=123, title="Frieren", year=2023)


def test_to_match_falls_back_to_english_title_and_null_year() -> None:
    item = {
        "id": 456,
        "title": {"romaji": None, "english": "Some Show"},
        "startDate": {"year": None},
    }

    match = _to_match(item)

    assert match == AniListMatch(media_id=456, title="Some Show", year=None)


def test_to_entry_returns_none_for_missing_entry() -> None:
    assert _to_entry(None) is None


def test_to_entry_parses_status_and_progress() -> None:
    entry = {"status": "CURRENT", "progress": 5}

    assert _to_entry(entry) == ("CURRENT", 5)


# --- search_media / get_list_entry / save_media_list_entry (task 2.3/2.4) ---


def test_search_media_returns_matches_from_page() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "data": {
                        "Page": {
                            "media": [
                                {
                                    "id": 1,
                                    "title": {"romaji": "Show A", "english": None},
                                    "startDate": {"year": 2020},
                                }
                            ]
                        }
                    }
                }
            )
        ]
    )
    client = AniListWriteClient(access_token=DUMMY_TOKEN, session=session)

    matches = client.search_media("Show A")

    assert matches == [AniListMatch(media_id=1, title="Show A", year=2020)]


def test_get_list_entry_returns_none_when_no_entry_exists() -> None:
    session = FakeSession(
        [FakeResponse({"data": {"Media": {"mediaListEntry": None}}})]
    )
    client = AniListWriteClient(access_token=DUMMY_TOKEN, session=session)

    assert client.get_list_entry(123) is None


def test_get_list_entry_returns_status_and_progress_when_present() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "data": {
                        "Media": {
                            "mediaListEntry": {"status": "COMPLETED", "progress": 12}
                        }
                    }
                }
            )
        ]
    )
    client = AniListWriteClient(access_token=DUMMY_TOKEN, session=session)

    assert client.get_list_entry(123) == ("COMPLETED", 12)


def test_save_media_list_entry_sends_mutation_and_returns_result() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "data": {
                        "SaveMediaListEntry": {
                            "id": 1,
                            "status": "COMPLETED",
                            "progress": 12,
                        }
                    }
                }
            )
        ]
    )
    client = AniListWriteClient(access_token=DUMMY_TOKEN, session=session)

    result = client.save_media_list_entry(media_id=123, status="COMPLETED", progress=12)

    assert result == ("COMPLETED", 12)
    url, kwargs = session.calls[0]
    body = kwargs["json"]
    assert body["variables"] == {"mediaId": 123, "status": "COMPLETED", "progress": 12}
    assert "SaveMediaListEntry" in body["query"]


# --- Confirm anonymous AniListClient is untouched (task 2.5/2.6) ---


def test_anonymous_anilist_client_module_is_byte_for_byte_unchanged() -> None:
    module_path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "hobby_anime"
        / "anilist.py"
    )
    digest = hashlib.sha256(module_path.read_bytes()).hexdigest()

    assert digest == "2e29e44dcd546da1f248d4d09cbae4ef5f010d52ace8a4c137c2060be243094b", (
        "src/hobby_anime/anilist.py must remain byte-for-byte unchanged; "
        "the anonymous seasonal-discovery client is out of scope for the "
        "authenticated write path."
    )
