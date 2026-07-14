from types import SimpleNamespace

import pytest

from hobby_anime.qbittorrent_client import QBittorrentGateway


class FakeClient:
    def __init__(self, result: str = "Ok.") -> None:
        self.result = result
        self.app = SimpleNamespace(web_api_version="2.11")
        self.created_categories: list[tuple[str, str]] = []
        self.added: list[dict[str, object]] = []

    def auth_log_in(self) -> None:
        return None

    def torrents_categories(self) -> dict[str, object]:
        return {}

    def torrents_create_category(self, category: str, save_path: str) -> None:
        self.created_categories.append((category, save_path))

    def torrents_add(self, **kwargs: object) -> str:
        self.added.append(kwargs)
        return self.result


def test_gateway_creates_category_and_adds_download() -> None:
    client = FakeClient()
    gateway = QBittorrentGateway("host", 8080, "user", "pass", "/data/torrents", "anime", client)

    gateway.add("magnet:?xt=example")

    assert client.created_categories == [("anime", "/data/torrents")]
    assert client.added[0]["save_path"] == "/data/torrents"


def test_gateway_rejects_unexpected_response() -> None:
    gateway = QBittorrentGateway(
        "host",
        8080,
        "user",
        "pass",
        "/data/torrents",
        "anime",
        FakeClient("Fails."),
    )

    with pytest.raises(RuntimeError):
        gateway.add("magnet:?xt=example")
