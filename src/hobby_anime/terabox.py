"""Minimal TeraBox client for public share links posted in Telegram channels.

TeraBox has no official download API for shared links. This client mimics the
web page flow and talks only to TeraBox itself, authenticated with the
``ndus`` cookie of a (secondary) TeraBox account:

1. Open the share link and follow redirects to the page that carries ``surl``.
2. Read ``jsToken`` and ``dp-logid`` from that page.
3. List the share with ``/share/list`` (folders are walked one level deep).
4. Stream each file from its ``dlink``.

The cookie is stored in a domain-scoped cookie jar, so it is never sent to
hosts outside TeraBox, not even after redirects. Expect this module to need
maintenance when TeraBox changes its web page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urlsplit

import requests

TERABOX_DOMAINS = (
    "terabox.com",
    "terabox.app",
    "teraboxapp.com",
    "terabox.fun",
    "teraboxlink.com",
    "teraboxshare.com",
    "terasharelink.com",
    "terafileshare.com",
    "1024terabox.com",
    "1024tera.com",
    "freeterabox.com",
    "4funbox.com",
    "mirrobox.com",
    "nephobox.com",
    "momerybox.com",
    "tibibox.com",
    "gibibox.com",
)
API_BASE = "https://www.terabox.app"
APP_ID = "250528"
PAGE_SIZE = 100
MAX_PAGES = 10
CHUNK_SIZE = 1024 * 1024
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

_DOMAIN_PATTERN = "|".join(re.escape(domain) for domain in TERABOX_DOMAINS)
_LINK_PATTERN = re.compile(
    rf"https?://(?:[a-z0-9-]+\.)*(?:{_DOMAIN_PATTERN})"
    r"/(?:s/[A-Za-z0-9_-]+|(?:sharing/link|wap/share/filelist)\?surl=[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_JS_TOKEN = re.compile(r"fn%28%22([0-9A-Za-z%]+?)%22%29")
_LOG_ID = re.compile(r"dp-logid=([0-9A-Za-z]+)")


class TeraBoxError(RuntimeError):
    """TeraBox answered, but not with what we needed."""


class TeraBoxAuthError(TeraBoxError):
    """The ndus cookie is missing, expired or not accepted."""


@dataclass(frozen=True)
class TeraBoxFile:
    fs_id: str
    name: str
    size: int
    dlink: str


def find_links(text: str, extra_urls: Iterable[str] = ()) -> list[str]:
    """Return unique TeraBox share links found in a message, in order."""
    found: list[str] = []
    for source in (text or "", *extra_urls):
        for match in _LINK_PATTERN.finditer(source or ""):
            link = match.group(0)
            if link not in found:
                found.append(link)
    return found


def is_terabox_host(host: str) -> bool:
    host = (host or "").casefold().rstrip(".")
    return any(host == domain or host.endswith(f".{domain}") for domain in TERABOX_DOMAINS)


def normalize_cookie(value: str) -> str:
    """Accept either the bare ndus value or a pasted ``ndus=...; other=...`` string."""
    value = (value or "").strip()
    match = re.search(r"(?:^|;\s*)ndus=([^;]+)", value)
    return (match.group(1) if match else value).strip()


class TeraBoxClient:
    def __init__(
        self,
        ndus_cookie: str,
        *,
        timeout_seconds: int = 30,
        session: Any | None = None,
    ) -> None:
        ndus = normalize_cookie(ndus_cookie)
        if not ndus:
            raise TeraBoxAuthError("TERABOX_COOKIE is empty")
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        cookies = getattr(self.session, "cookies", None)
        if cookies is not None:
            for domain in TERABOX_DOMAINS:
                cookies.set("ndus", ndus, domain=f".{domain}", path="/")
                cookies.set("lang", "en", domain=f".{domain}", path="/")

    def resolve(self, link: str, max_files: int = 10) -> list[TeraBoxFile]:
        """List the files behind a share link, folders included one level deep."""
        if not find_links(link):
            raise TeraBoxError(f"Not a TeraBox share link: {link}")

        landing = self.session.get(link, timeout=self.timeout_seconds, allow_redirects=True)
        _raise_for_status(landing, "open share link")
        final = urlsplit(landing.url)
        if not is_terabox_host(final.hostname or ""):
            raise TeraBoxError(f"Share link redirected outside TeraBox: {final.hostname}")
        surl = (parse_qs(final.query).get("surl") or [""])[0] or _surl_from_path(final.path)
        if not surl:
            raise TeraBoxError("Share link did not resolve to a share page (link removed?)")

        page = landing.text or ""
        js_token = _first(_JS_TOKEN, page)
        log_id = _first(_LOG_ID, page)
        if not js_token or not log_id:
            raise TeraBoxError("Could not read jsToken/logid from the share page; TeraBox may have changed")

        base_params = {
            "app_id": APP_ID,
            "web": "1",
            "channel": "dubox",
            "clienttype": "0",
            "jsToken": unquote(js_token),
            "dp-logid": log_id,
            "num": str(PAGE_SIZE),
            "by": "name",
            "order": "asc",
            "site_referer": landing.url,
            "shorturl": surl,
        }

        files: list[TeraBoxFile] = []
        for entry in self._list(base_params, {"root": "1"}):
            if len(files) >= max_files:
                break
            if _is_dir(entry):
                for child in self._list(base_params, {"dir": str(entry.get("path", ""))}):
                    if len(files) >= max_files:
                        break
                    if not _is_dir(child):
                        files.append(_to_file(child))
            else:
                files.append(_to_file(entry))
        return files

    def download(self, file: TeraBoxFile, target: Path) -> None:
        """Stream a file to ``target``; resumes a partial file when the server allows it."""
        url = urlsplit(file.dlink)
        if url.scheme != "https" or not is_terabox_host(url.hostname or ""):
            raise TeraBoxError(f"Refusing download link outside TeraBox: {url.hostname}")

        existing = target.stat().st_size if target.exists() else 0
        headers = {"Referer": "https://www.terabox.com/"}
        if 0 < existing < file.size:
            headers["Range"] = f"bytes={existing}-"
        elif existing:
            target.unlink()
            existing = 0

        with self.session.get(
            file.dlink,
            headers=headers,
            stream=True,
            timeout=self.timeout_seconds,
            allow_redirects=True,
        ) as response:
            _raise_for_status(response, "download file")
            content_type = str(response.headers.get("Content-Type", "")).casefold()
            if "text/html" in content_type or "application/json" in content_type:
                raise TeraBoxAuthError("TeraBox returned a page instead of the file (cookie expired?)")
            mode = "ab" if existing and response.status_code == 206 else "wb"
            with target.open(mode) as handle:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        handle.write(chunk)

    def _list(self, base_params: dict[str, str], extra: dict[str, str]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            response = self.session.get(
                f"{API_BASE}/share/list",
                params={**base_params, **extra, "page": str(page)},
                timeout=self.timeout_seconds,
            )
            _raise_for_status(response, "list share")
            try:
                data = response.json()
            except ValueError as exc:
                raise TeraBoxError("TeraBox share list was not JSON") from exc
            errno = int(data.get("errno", 0) or 0)
            if errno:
                message = data.get("errmsg") or data.get("show_msg") or "unknown error"
                if errno in {-6, 9019, 4000020}:
                    raise TeraBoxAuthError(f"TeraBox rejected the session (errno {errno}): {message}")
                raise TeraBoxError(f"TeraBox share list failed (errno {errno}): {message}")
            batch = data.get("list") or []
            entries.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
        return entries


def _to_file(entry: dict[str, Any]) -> TeraBoxFile:
    dlink = str(entry.get("dlink") or "")
    if not dlink:
        raise TeraBoxAuthError("Share list has no download link; the ndus cookie is missing or expired")
    return TeraBoxFile(
        fs_id=str(entry.get("fs_id", "")),
        name=str(entry.get("server_filename") or entry.get("path", "").rsplit("/", 1)[-1]),
        size=int(entry.get("size") or 0),
        dlink=dlink,
    )


def _is_dir(entry: dict[str, Any]) -> bool:
    return str(entry.get("isdir", "0")) in {"1", "True", "true"}


def _surl_from_path(path: str) -> str:
    match = re.search(r"/s/1?([A-Za-z0-9_-]+)", path)
    return match.group(1) if match else ""


def _first(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group(1) if match else ""


def _raise_for_status(response: Any, action: str) -> None:
    status = int(getattr(response, "status_code", 200))
    if status in {401, 403}:
        raise TeraBoxAuthError(f"TeraBox refused to {action} (HTTP {status})")
    if status >= 400:
        raise TeraBoxError(f"TeraBox could not {action} (HTTP {status})")
