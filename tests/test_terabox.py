from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from requests.cookies import RequestsCookieJar

from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.models import MediaInspection
from hobby_anime.telegram_listener import TelegramIngestor, message_urls
from hobby_anime.terabox import (
    TeraBoxAuthError,
    TeraBoxClient,
    TeraBoxError,
    TeraBoxFile,
    find_links,
    is_terabox_host,
    normalize_cookie,
)

MB = 1024**2
SHARE = "https://1024terabox.com/s/1vkIqaxJeaizZRMwvh2iJSQ"
LANDING = "https://www.1024tera.com/sharing/link?surl=vkIqaxJeaizZRMwvh2iJSQ"
PAGE = '<script>x=decodeURIComponent("fn%28%22ABC123TOKEN%22%29");u="/api?dp-logid=998877&a=1"</script>'


class FakeResponse:
    def __init__(
        self,
        *,
        url: str = "",
        text: str = "",
        json_data: Any = None,
        status_code: int = 200,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.url = url
        self.text = text
        self._json = json_data
        self.status_code = status_code
        self._content = content
        self.headers = headers or {"Content-Type": "application/octet-stream"}

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def iter_content(self, chunk_size: int = 1):
        for start in range(0, len(self._content), chunk_size):
            yield self._content[start : start + chunk_size]

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class FakeSession:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.headers: dict[str, str] = {}
        self.cookies = RequestsCookieJar()
        self.routes = routes
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        route = self.routes[url]
        return route(kwargs) if callable(route) else route


def _listing(entries_by_key: dict[str, list[dict[str, Any]]]):
    def respond(kwargs: dict[str, Any]) -> FakeResponse:
        params = kwargs["params"]
        key = "root" if params.get("root") else params.get("dir", "")
        return FakeResponse(json_data={"errno": 0, "list": entries_by_key.get(key, [])})

    return respond


def _video(fs_id: int, name: str, size: int = 2 * MB) -> dict[str, Any]:
    return {
        "fs_id": fs_id,
        "server_filename": name,
        "size": size,
        "isdir": 0,
        "dlink": f"https://d.terabox.app/file/{fs_id}",
    }


def _client(routes: dict[str, Any]) -> tuple[TeraBoxClient, FakeSession]:
    session = FakeSession(routes)
    return TeraBoxClient("ndus=SECRET; lang=en", session=session), session


def test_find_links_in_text_and_hidden_entities() -> None:
    text = f"Episodio 5 Latino\n{SHARE}\notro {SHARE}"
    hidden = ["https://www.terabox.app/sharing/link?surl=abc_DEF-1", "https://example.com/s/nope"]
    assert find_links(text, hidden) == [SHARE, "https://www.terabox.app/sharing/link?surl=abc_DEF-1"]
    assert find_links("https://ouo.io/abc https://mega.nz/file/x") == []


def test_host_check_and_cookie_normalization() -> None:
    assert is_terabox_host("d-jp01.terabox.app")
    assert is_terabox_host("1024terabox.com")
    assert not is_terabox_host("terabox.app.evil.com")
    assert not is_terabox_host("notterabox.com")
    assert normalize_cookie("lang=en; ndus=Yabc123; other=1") == "Yabc123"
    assert normalize_cookie("  Yabc123 ") == "Yabc123"


def test_cookie_is_scoped_to_terabox_domains() -> None:
    client, session = _client({})
    domains = {cookie.domain for cookie in session.cookies if cookie.name == "ndus"}
    assert ".terabox.app" in domains and ".1024terabox.com" in domains
    assert "Cookie" not in session.headers
    assert all(is_terabox_host(domain.lstrip(".")) for domain in domains)


def test_empty_cookie_is_rejected() -> None:
    with pytest.raises(TeraBoxAuthError):
        TeraBoxClient("  ", session=FakeSession({}))


def test_resolve_lists_files_and_walks_one_folder_level() -> None:
    folder = {"fs_id": 9, "server_filename": "Temporada 1", "isdir": 1, "path": "/Temporada 1"}
    client, session = _client(
        {
            SHARE: FakeResponse(url=LANDING, text=PAGE),
            "https://www.terabox.app/share/list": _listing(
                {
                    "root": [_video(1, "Show - 01.mkv"), folder],
                    "/Temporada 1": [_video(2, "Show - 02.mkv"), _video(3, "Show - 03.mkv")],
                }
            ),
        }
    )

    files = client.resolve(SHARE)

    assert [file.name for file in files] == ["Show - 01.mkv", "Show - 02.mkv", "Show - 03.mkv"]
    params = session.calls[1][1]["params"]
    assert params["jsToken"] == "ABC123TOKEN"
    assert params["dp-logid"] == "998877"
    assert params["shorturl"] == "vkIqaxJeaizZRMwvh2iJSQ"
    assert client.resolve(SHARE, max_files=2)[-1].name == "Show - 02.mkv"


def test_resolve_errors() -> None:
    client, _ = _client({SHARE: FakeResponse(url="https://evil.example/sharing/link?surl=x", text=PAGE)})
    with pytest.raises(TeraBoxError, match="outside TeraBox"):
        client.resolve(SHARE)

    client, _ = _client({SHARE: FakeResponse(url=LANDING, text="<html>no tokens</html>")})
    with pytest.raises(TeraBoxError, match="jsToken"):
        client.resolve(SHARE)

    client, _ = _client(
        {
            SHARE: FakeResponse(url=LANDING, text=PAGE),
            "https://www.terabox.app/share/list": FakeResponse(json_data={"errno": 105, "errmsg": "gone"}),
        }
    )
    with pytest.raises(TeraBoxError, match="errno 105"):
        client.resolve(SHARE)

    no_dlink = dict(_video(1, "Show - 01.mkv"), dlink="")
    client, _ = _client(
        {
            SHARE: FakeResponse(url=LANDING, text=PAGE),
            "https://www.terabox.app/share/list": _listing({"root": [no_dlink]}),
        }
    )
    with pytest.raises(TeraBoxAuthError, match="cookie"):
        client.resolve(SHARE)

    with pytest.raises(TeraBoxError, match="Not a TeraBox"):
        client.resolve("https://mega.nz/file/abc")


def test_download_streams_and_refuses_foreign_or_html_responses(tmp_path: Path) -> None:
    file = TeraBoxFile("1", "Show - 01.mkv", 5, "https://d.terabox.app/file/1")
    client, _ = _client({file.dlink: FakeResponse(content=b"12345")})
    target = tmp_path / "Show.part"
    client.download(file, target)
    assert target.read_bytes() == b"12345"

    with pytest.raises(TeraBoxError, match="outside TeraBox"):
        client.download(replace(file, dlink="https://evil.example/file"), tmp_path / "x.part")

    client, _ = _client({file.dlink: FakeResponse(headers={"Content-Type": "text/html"})})
    with pytest.raises(TeraBoxAuthError):
        client.download(file, tmp_path / "y.part")


def test_download_resumes_partial_file(tmp_path: Path) -> None:
    file = TeraBoxFile("1", "Show - 01.mkv", 5, "https://d.terabox.app/file/1")
    target = tmp_path / "Show.part"
    target.write_bytes(b"12")
    seen: dict[str, Any] = {}

    def respond(kwargs: dict[str, Any]) -> FakeResponse:
        seen.update(kwargs["headers"])
        return FakeResponse(content=b"345", status_code=206)

    client, _ = _client({file.dlink: respond})
    client.download(file, target)
    assert seen["Range"] == "bytes=2-"
    assert target.read_bytes() == b"12345"


class FakeTeraBox:
    def __init__(self, files: list[TeraBoxFile], error: Exception | None = None) -> None:
        self.files = files
        self.error = error
        self.downloaded: list[str] = []

    def resolve(self, link: str, max_files: int = 10) -> list[TeraBoxFile]:
        if self.error:
            raise self.error
        return self.files[:max_files]

    def download(self, file: TeraBoxFile, target: Path) -> None:
        self.downloaded.append(file.name)
        target.write_bytes(b"\0" * file.size)


class AcceptAll:
    def inspect(self, content_path: Path) -> MediaInspection:
        return MediaInspection(accepted=True, audio_languages=("spa",), reason="ok")


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, report: str) -> list[str]:
        self.messages.append(report)
        return ["test"]


@pytest.fixture
def tg_settings(settings: Settings, tmp_path: Path) -> Settings:
    return replace(
        settings,
        telegram_quarantine_path=tmp_path / "torrents" / "telegram" / "quarantine",
        telegram_verified_path=tmp_path / "torrents" / "verified" / "telegram",
        sonarr_verified_root=tmp_path / "torrents" / "verified",
        sonarr_enabled=True,
        minimum_free_space_gb=0,
        telegram_min_file_mb=1,
        terabox_enabled=True,
        terabox_cookie="ndus",
        notify_on_verification=False,
    )


def _ingestor(settings: Settings, terabox: FakeTeraBox, notifier: RecordingNotifier | None = None):
    database = TrackingDatabase(settings.database_path)
    database.initialize()

    async def no_telegram_download(message: Any, path: Path) -> None:
        raise AssertionError("telegram download should not be used for links")

    ingestor = TelegramIngestor(
        settings,
        download=no_telegram_download,
        database=database,
        inspector=AcceptAll(),
        notifier=notifier,
        terabox=terabox,
    )
    return ingestor, database


def _link_message(message_id: int, text: str, entities: list[Any] | None = None):
    return SimpleNamespace(chat_id=-100777, id=message_id, file=None, message=text, entities=entities or [])


def test_ingestor_downloads_videos_from_a_terabox_link(tg_settings: Settings) -> None:
    terabox = FakeTeraBox(
        [
            TeraBoxFile("11", "Show - 01 Latino.mkv", 2 * MB, "https://d.terabox.app/1"),
            TeraBoxFile("12", "readme.txt", 2 * MB, "https://d.terabox.app/2"),
        ]
    )
    ingestor, database = _ingestor(tg_settings, terabox)

    outcome = asyncio.run(ingestor.handle(_link_message(5, f"Nuevo capítulo {SHARE}")))

    assert terabox.downloaded == ["Show - 01 Latino.mkv"]
    assert outcome == "filtered"  # last file in the share was the .txt
    assert database.verification_status("tg-100777-5-tb11") == "verified"
    assert (tg_settings.telegram_verified_path / "tg-100777-5-tb11" / "Show - 01 Latino.mkv").is_file()
    assert database.import_status("tg-100777-5-tb11") == "pending"

    # Same message again (backfill/restart) does not download twice.
    asyncio.run(ingestor.handle(_link_message(5, f"Nuevo capítulo {SHARE}")))
    assert terabox.downloaded == ["Show - 01 Latino.mkv"]


def test_ingestor_reads_hidden_links_from_entities(tg_settings: Settings) -> None:
    terabox = FakeTeraBox([TeraBoxFile("21", "Show - 02.mkv", 2 * MB, "https://d.terabox.app/1")])
    ingestor, _ = _ingestor(tg_settings, terabox)
    message = _link_message(6, "Descargar aquí", [SimpleNamespace(url=SHARE)])
    assert message_urls(message) == [SHARE]
    assert asyncio.run(ingestor.handle(message)) == "verified"


def test_ingestor_alerts_once_when_cookie_expires(tg_settings: Settings) -> None:
    notifier = RecordingNotifier()
    terabox = FakeTeraBox([], error=TeraBoxAuthError("cookie expired"))
    ingestor, _ = _ingestor(tg_settings, terabox, notifier)

    assert asyncio.run(ingestor.handle(_link_message(7, SHARE))) == "error"
    assert asyncio.run(ingestor.handle(_link_message(8, SHARE))) == "error"
    assert len(notifier.messages) == 1
    assert "TERABOX_COOKIE" in notifier.messages[0]


def test_links_are_ignored_when_terabox_is_disabled(tg_settings: Settings) -> None:
    ingestor, _ = _ingestor(tg_settings, FakeTeraBox([]))
    ingestor.terabox = None
    assert asyncio.run(ingestor.handle(_link_message(9, SHARE))) == "no-file"


def test_validate_requires_cookie_when_enabled(tg_settings: Settings) -> None:
    settings = replace(
        tg_settings,
        telegram_source_enabled=True,
        telegram_api_id=1,
        telegram_api_hash="h",
        telegram_channels=("@c",),
        terabox_cookie="",
    )
    with pytest.raises(ValueError, match="TERABOX_COOKIE"):
        settings.validate_telegram()
    assert "SECRET" not in repr(replace(settings, terabox_cookie="SECRET"))
