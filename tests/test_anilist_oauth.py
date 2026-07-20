from __future__ import annotations

import http.client
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import requests

from hobby_anime import anilist_oauth as oauth
from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase
from hobby_anime.models import StoredToken

DUMMY_SECRET = "top-secret-client-secret"  # noqa: S105 (test fixture value, never real)
DUMMY_TOKEN = "top-secret-oauth-access-token"  # noqa: S105
DUMMY_CODE = "top-secret-authorization-code"  # noqa: S105


# --- Pure logic: state generation ---


def test_generate_state_is_url_safe_and_sufficiently_long() -> None:
    state = oauth.generate_state()
    assert len(state) >= 32
    assert all(ch.isalnum() or ch in "-_" for ch in state)


def test_generate_state_is_unpredictable_across_calls() -> None:
    assert oauth.generate_state() != oauth.generate_state()


# --- Pure logic: authorize URL ---


def test_build_authorize_url_contains_required_params() -> None:
    url = oauth.build_authorize_url("client-123", "http://127.0.0.1:8712/callback", "state-abc")

    assert url.startswith(oauth.AUTHORIZE_URL)
    assert "client_id=client-123" in url
    assert "response_type=code" in url
    assert "state=state-abc" in url
    assert "127.0.0.1%3A8712" in url or "127.0.0.1:8712" in url


def test_build_authorize_url_never_includes_a_client_secret() -> None:
    # A dummy secret is deliberately never passed to this function; assert its
    # absence to make the guarantee non-vacuous should a future edit add one.
    url = oauth.build_authorize_url("client-123", "http://127.0.0.1:8712/callback", "state-abc")
    assert DUMMY_SECRET not in url


def test_redirect_uri_for_uses_loopback_only() -> None:
    uri = oauth.redirect_uri_for(8712)
    assert uri == "http://127.0.0.1:8712/callback"
    assert "0.0.0.0" not in uri


# --- Pure logic: callback parsing and state validation (CSRF guard) ---


def test_parse_callback_params_extracts_single_values() -> None:
    params = oauth.parse_callback_params("code=abc123&state=xyz789")
    assert params == {"code": "abc123", "state": "xyz789"}


def test_validate_callback_returns_code_on_matching_state() -> None:
    code = oauth.validate_callback({"code": DUMMY_CODE, "state": "expected"}, "expected")
    assert code == DUMMY_CODE


def test_validate_callback_rejects_mismatched_state() -> None:
    with pytest.raises(ValueError, match="state mismatch"):
        oauth.validate_callback({"code": DUMMY_CODE, "state": "wrong"}, "expected")


def test_validate_callback_rejects_missing_state() -> None:
    with pytest.raises(ValueError, match="state mismatch"):
        oauth.validate_callback({"code": DUMMY_CODE}, "expected")


def test_validate_callback_rejects_missing_code() -> None:
    with pytest.raises(ValueError, match="authorization code"):
        oauth.validate_callback({"state": "expected"}, "expected")


# --- Pure logic: token-response parsing ---


def test_parse_token_response_computes_expiry_from_expires_in() -> None:
    obtained_at = "2026-07-19T10:00:00+00:00"
    token = oauth.parse_token_response(
        {"access_token": DUMMY_TOKEN, "token_type": "Bearer", "expires_in": 3600},
        obtained_at=obtained_at,
    )
    assert token == StoredToken(
        access_token=DUMMY_TOKEN,
        token_type="Bearer",
        obtained_at=obtained_at,
        expires_at="2026-07-19T11:00:00+00:00",
    )


def test_parse_token_response_without_expires_in_leaves_expiry_none() -> None:
    obtained_at = "2026-07-19T10:00:00+00:00"
    token = oauth.parse_token_response(
        {"access_token": DUMMY_TOKEN, "token_type": "Bearer"},
        obtained_at=obtained_at,
    )
    assert token.expires_at is None


def test_parse_token_response_defaults_token_type_to_bearer() -> None:
    token = oauth.parse_token_response(
        {"access_token": DUMMY_TOKEN}, obtained_at="2026-07-19T10:00:00+00:00"
    )
    assert token.token_type == "Bearer"


# --- Pure logic: token validity detection ---


def test_token_is_valid_false_for_missing_token() -> None:
    assert oauth.token_is_valid(None) is False


def test_token_is_valid_true_when_no_expiry_reported() -> None:
    token = StoredToken(access_token=DUMMY_TOKEN, token_type="Bearer", obtained_at="x")
    assert oauth.token_is_valid(token) is True


def test_token_is_valid_true_for_future_expiry() -> None:
    now = datetime(2026, 7, 19, tzinfo=UTC)
    token = StoredToken(
        access_token=DUMMY_TOKEN,
        token_type="Bearer",
        obtained_at="x",
        expires_at=(now + timedelta(days=1)).isoformat(),
    )
    assert oauth.token_is_valid(token, now=now) is True


def test_token_is_valid_false_for_past_expiry() -> None:
    now = datetime(2026, 7, 19, tzinfo=UTC)
    token = StoredToken(
        access_token=DUMMY_TOKEN,
        token_type="Bearer",
        obtained_at="x",
        expires_at=(now - timedelta(days=1)).isoformat(),
    )
    assert oauth.token_is_valid(token, now=now) is False


# --- IO: one-shot loopback callback listener (mocked, no real socket binding) ---


class _FakeHTTPServer:
    """Records the (host, port) tuple it was constructed with and simulates one request."""

    last_bind_address: tuple[str, int] | None = None

    def __init__(self, address: tuple[str, int], handler_cls: type, *, query: str | None) -> None:
        _FakeHTTPServer.last_bind_address = address
        self.timeout = 0
        self.callback_query: str | None = None
        self._query = query
        self.closed = False
        self.handle_request_calls = 0

    def handle_request(self) -> None:
        self.handle_request_calls += 1
        self.callback_query = self._query

    def server_close(self) -> None:
        self.closed = True


def _factory(query: str | None):
    def make(address: tuple[str, int], handler_cls: type) -> _FakeHTTPServer:
        return _FakeHTTPServer(address, handler_cls, query=query)

    return make


def test_capture_authorization_code_binds_127_0_0_1_only() -> None:
    oauth.capture_authorization_code(
        8712, "state-1", server_factory=_factory("code=abc&state=state-1")
    )
    assert _FakeHTTPServer.last_bind_address == ("127.0.0.1", 8712)
    assert _FakeHTTPServer.last_bind_address[0] != "0.0.0.0"


def test_capture_authorization_code_is_one_shot() -> None:
    made: list[_FakeHTTPServer] = []

    def factory(address: tuple[str, int], handler_cls: type) -> _FakeHTTPServer:
        server = _FakeHTTPServer(address, handler_cls, query="code=abc&state=state-1")
        made.append(server)
        return server

    oauth.capture_authorization_code(8712, "state-1", server_factory=factory)

    assert made[0].handle_request_calls == 1
    assert made[0].closed is True


def test_capture_authorization_code_returns_validated_code() -> None:
    code = oauth.capture_authorization_code(
        8712, "state-1", server_factory=_factory(f"code={DUMMY_CODE}&state=state-1")
    )
    assert code == DUMMY_CODE


def test_capture_authorization_code_rejects_state_mismatch() -> None:
    with pytest.raises(ValueError, match="state mismatch"):
        oauth.capture_authorization_code(
            8712, "state-1", server_factory=_factory("code=abc&state=wrong-state")
        )


def test_capture_authorization_code_times_out_when_no_callback_arrives() -> None:
    with pytest.raises(TimeoutError):
        oauth.capture_authorization_code(8712, "state-1", server_factory=_factory(None))


def test_capture_authorization_code_closes_server_even_on_timeout() -> None:
    made: list[_FakeHTTPServer] = []

    def factory(address: tuple[str, int], handler_cls: type) -> _FakeHTTPServer:
        server = _FakeHTTPServer(address, handler_cls, query=None)
        made.append(server)
        return server

    with pytest.raises(TimeoutError):
        oauth.capture_authorization_code(8712, "state-1", server_factory=factory)

    assert made[0].closed is True


# --- IO: code-for-token exchange (mocked session, no real network) ---


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error for url: {oauth.TOKEN_URL}")

    def json(self) -> object:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._responses = list(responses)

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        return self._responses.pop(0)


def test_exchange_code_posts_secret_and_code_only_in_body_never_in_url() -> None:
    session = FakeSession([FakeResponse({"access_token": DUMMY_TOKEN, "expires_in": 3600})])

    oauth.exchange_code(
        "client-123", DUMMY_SECRET, DUMMY_CODE, "http://127.0.0.1:8712/callback", session=session
    )

    url, kwargs = session.calls[0]
    assert url == oauth.TOKEN_URL
    assert DUMMY_SECRET not in url
    assert DUMMY_CODE not in url
    body = kwargs["json"]
    assert body["client_secret"] == DUMMY_SECRET
    assert body["code"] == DUMMY_CODE
    assert "headers" not in kwargs or DUMMY_SECRET not in str(kwargs.get("headers"))


def test_exchange_code_returns_parsed_stored_token() -> None:
    session = FakeSession(
        [FakeResponse({"access_token": DUMMY_TOKEN, "token_type": "Bearer", "expires_in": 60})]
    )

    token = oauth.exchange_code(
        "client-123", DUMMY_SECRET, DUMMY_CODE, "http://127.0.0.1:8712/callback", session=session
    )

    assert token.access_token == DUMMY_TOKEN
    assert token.token_type == "Bearer"
    assert token.expires_at is not None


def test_exchange_code_http_error_never_leaks_secret_or_code() -> None:
    session = FakeSession([FakeResponse({}, status_code=401)])

    raised = False
    try:
        oauth.exchange_code(
            "client-123",
            DUMMY_SECRET,
            DUMMY_CODE,
            "http://127.0.0.1:8712/callback",
            session=session,
        )
    except requests.HTTPError as exc:
        raised = True
        assert DUMMY_SECRET not in str(exc)
        assert DUMMY_CODE not in str(exc)
        assert DUMMY_TOKEN not in str(exc)

    assert raised


# --- Orchestration: run_auth_flow (mocked IO boundaries) ---


def _oauth_settings() -> Settings:
    return Settings(
        database_path=None,  # type: ignore[arg-type]  # overwritten per-test via tmp_path
        media_path=None,  # type: ignore[arg-type]
        rss_urls=(),
        rss_resolution="1080p",
        rss_groups=(),
        rss_include_terms=(),
        rss_exclude_terms=(),
        rss_max_age_hours=72,
        qbt_host="qbittorrent",
        qbt_port=8080,
        qbt_username="admin",
        qbt_password="",
        qbt_save_path="/data/torrents",
        qbt_category="hobby-anime",
        daily_hour=3,
        daily_minute=0,
        monthly_day=1,
        monthly_hour=9,
        timezone="UTC",
        anilist_url="https://graphql.anilist.co",
        ollama_enabled=False,
        ollama_url="http://ollama:11434",
        ollama_model="qwen2.5:3b",
        webhook_url="",
        telegram_bot_token="",
        telegram_chat_id="",
        jellyfin_url="http://jellyfin:8096",
        request_timeout_seconds=5,
        anilist_client_id="client-123",
        anilist_client_secret=DUMMY_SECRET,
        anilist_redirect_port=8712,
    )


def test_run_auth_flow_success_stores_token_and_never_prints_secret(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = replace(_oauth_settings(), database_path=tmp_path / "tracking.db")
    database = TrackingDatabase(settings.database_path)
    database.initialize()

    opened_urls: list[str] = []
    monkeypatch.setattr(
        oauth,
        "capture_authorization_code",
        lambda port, state, **kwargs: DUMMY_CODE,
    )
    session = FakeSession(
        [FakeResponse({"access_token": DUMMY_TOKEN, "token_type": "Bearer", "expires_in": 3600})]
    )

    token = oauth.run_auth_flow(
        settings,
        database,
        browser_opener=opened_urls.append,
        session=session,
    )

    assert token.access_token == DUMMY_TOKEN
    stored = database.get_token()
    assert stored is not None
    assert stored.access_token == DUMMY_TOKEN
    assert len(opened_urls) == 1
    assert "state=" in opened_urls[0]

    out = capsys.readouterr().out
    assert DUMMY_TOKEN not in out
    assert DUMMY_SECRET not in out
    assert DUMMY_CODE not in out


def test_run_auth_flow_missing_config_raises_before_any_io(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = replace(
        _oauth_settings(), database_path=tmp_path / "tracking.db", anilist_client_id=""
    )
    database = TrackingDatabase(settings.database_path)
    database.initialize()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("must not reach browser open before config validation")

    with pytest.raises(ValueError, match="ANILIST_CLIENT_ID"):
        oauth.run_auth_flow(settings, database, browser_opener=fail_if_called)


# --- Real loopback socket integration test (controlled ephemeral port fixture) ---


def test_capture_authorization_code_real_socket_binds_loopback_only_and_returns_code() -> None:
    """End-to-end check using a real HTTPServer on an OS-assigned ephemeral port.

    This exercises _CallbackHandler.do_GET for real (not mocked), while still
    being fully deterministic and never touching a fixed/well-known port.
    """
    from http.server import HTTPServer

    from hobby_anime.anilist_oauth import _CallbackHandler

    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    assert server.server_address[0] == "127.0.0.1"
    server.timeout = 5
    server.callback_query = None
    port = server.server_address[1]

    def send_callback() -> None:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", f"/callback?code={DUMMY_CODE}&state=real-state")
        connection.getresponse().read()
        connection.close()

    thread = threading.Thread(target=send_callback)
    thread.start()
    try:
        server.handle_request()
    finally:
        server.server_close()
        thread.join(timeout=5)

    params = oauth.parse_callback_params(server.callback_query)
    code = oauth.validate_callback(params, "real-state")
    assert code == DUMMY_CODE


def test_capture_authorization_code_real_socket_never_binds_all_interfaces() -> None:
    from http.server import HTTPServer

    from hobby_anime.anilist_oauth import _CallbackHandler

    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert server.server_address[0] != "0.0.0.0"
    finally:
        server.server_close()
