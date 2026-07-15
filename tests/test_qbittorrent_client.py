from types import SimpleNamespace

import pytest

from hobby_anime.qbittorrent_client import QBittorrentGateway


class FakeClient:
    def __init__(self, result: object = "Ok.") -> None:
        self.result = result
        self.app = SimpleNamespace(web_api_version="2.11")
        self.created_categories: list[tuple[str, str]] = []
        self.added: list[dict[str, object]] = []
        self.locations: list[dict[str, object]] = []
        self.categories: list[dict[str, object]] = []
        self.stopped: list[str] = []
        self.current_save_path = "/data/torrents/quarantine"

    def auth_log_in(self) -> None:
        return None

    def torrents_categories(self) -> dict[str, object]:
        return {}

    def torrents_create_category(self, name: str, save_path: str) -> None:
        self.created_categories.append((name, save_path))

    def torrents_add(self, **kwargs: object) -> object:
        self.added.append(kwargs)
        return self.result

    def torrents_info(self, **kwargs: object) -> list[dict[str, str]]:
        return [
            {
                "hash": "abc123",
                "name": "Episode",
                "content_path": f"{self.current_save_path}/episode.mkv",
                "save_path": self.current_save_path,
                "state": "uploading",
            }
        ]

    def torrents_set_location(self, **kwargs: object) -> None:
        self.locations.append(kwargs)
        self.current_save_path = str(kwargs["location"])

    def torrents_set_category(self, **kwargs: object) -> None:
        self.categories.append(kwargs)

    def torrents_stop(self, torrent_hashes: str) -> None:
        self.stopped.append(torrent_hashes)


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


def test_gateway_accepts_modern_add_metadata() -> None:
    client = FakeClient(
        {
            "success_count": 1,
            "pending_count": 0,
            "failure_count": 0,
            "added_torrent_ids": ["abc123"],
        }
    )
    gateway = QBittorrentGateway(
        "host",
        8080,
        "user",
        "pass",
        "/data/torrents/quarantine",
        "anime",
        client,
    )

    gateway.add("magnet:?xt=example")

    assert len(client.added) == 1


def test_gateway_lists_and_classifies_completed_downloads() -> None:
    client = FakeClient()
    gateway = QBittorrentGateway(
        "host",
        8080,
        "user",
        "pass",
        "/data/torrents/quarantine",
        "anime",
        client,
    )

    downloads = gateway.completed(("anime", "sonarr"))
    promoted = gateway.accept("abc123", "/data/torrents/verified", "anime-verified")
    gateway.reject("def456", "anime-rejected")

    assert downloads[0].torrent_hash == "abc123"
    assert downloads[0].content_path.name == "episode.mkv"
    assert str(promoted.content_path) == client.current_save_path + "/episode.mkv"
    assert client.locations[0]["location"] == "/data/torrents/verified"
    assert client.categories[0]["category"] == "anime-verified"
    assert client.stopped == ["def456"]
    assert client.categories[1]["category"] == "anime-rejected"
