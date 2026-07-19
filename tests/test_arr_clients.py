import requests

from hobby_anime.arr_clients import BazarrClient, ProwlarrClient


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        return FakeResponse({"version": "1.0"})


def test_prowlarr_uses_header_authentication() -> None:
    session = FakeSession()
    client = ProwlarrClient("http://prowlarr:9696", "secret", session=session)

    client.status()

    assert session.calls[0][0].endswith("/api/v1/system/status")
    assert session.calls[0][1]["headers"]["X-Api-Key"] == "secret"


def test_bazarr_uses_header_authentication() -> None:
    session = FakeSession()
    client = BazarrClient("http://bazarr:6767", "secret", session=session)

    client.status()

    url, kwargs = session.calls[0]
    assert url.endswith("/api/system/status")
    assert kwargs["headers"]["X-Api-Key"] == "secret"
    assert "params" not in kwargs
    assert "secret" not in url


def test_bazarr_http_error_does_not_leak_key_in_url() -> None:
    session = FakeSession()
    client = BazarrClient("http://bazarr:6767", "top-secret-key", session=session)

    client.status()

    url = session.calls[0][0]
    try:
        raise requests.HTTPError(f"404 Client Error: Not Found for url: {url}")
    except requests.HTTPError as exc:
        assert "top-secret-key" not in str(exc)
