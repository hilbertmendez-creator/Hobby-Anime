from __future__ import annotations

import secrets
import webbrowser
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit

import requests

from hobby_anime.models import StoredToken

if TYPE_CHECKING:
    from hobby_anime.config import Settings
    from hobby_anime.database import TrackingDatabase

AUTHORIZE_URL = "https://anilist.co/api/v2/oauth/authorize"
TOKEN_URL = "https://anilist.co/api/v2/oauth/token"

# --- Pure logic (no IO): state, URL building, callback validation, token parsing ---


def generate_state() -> str:
    """Generate a CSPRNG state token used to defend the callback against CSRF."""
    return secrets.token_urlsafe(32)


def build_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Build the AniList authorization-code consent URL. Never includes the client secret."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"

def redirect_uri_for(port: int) -> str:
    return f"http://127.0.0.1:{port}/callback"


def parse_callback_params(query_string: str) -> dict[str, str]:
    """Parse the raw callback query string into a flat single-valued dict."""
    parsed = parse_qs(query_string)
    return {key: values[0] for key, values in parsed.items() if values}


def validate_callback(params: dict[str, str], expected_state: str) -> str:
    """Return the authorization code from validated callback params.

    Rejects the callback (raises ValueError) when the `state` is missing or
    does not match the state issued for this flow — this is the CSRF guard.
    """
    if params.get("state") != expected_state:
        raise ValueError("OAuth callback state mismatch; rejecting to prevent CSRF")
    code = params.get("code")
    if not code:
        raise ValueError("OAuth callback did not include an authorization code")
    return code


def parse_token_response(payload: dict[str, Any], *, obtained_at: str) -> StoredToken:
    """Parse an AniList token-exchange JSON response into a StoredToken."""
    access_token = payload["access_token"]
    token_type = payload.get("token_type", "Bearer")
    expires_in = payload.get("expires_in")
    expires_at: str | None = None
    if expires_in is not None:
        obtained = datetime.fromisoformat(obtained_at)
        expires_at = (obtained + timedelta(seconds=int(expires_in))).isoformat()
    return StoredToken(
        access_token=access_token,
        token_type=token_type,
        obtained_at=obtained_at,
        expires_at=expires_at,
    )


def token_is_valid(token: StoredToken | None, *, now: datetime | None = None) -> bool:
    """Detect whether a stored token is present and not expired.

    A token without an `expires_at` is treated as valid (AniList access tokens
    default to a long-lived expiry set by the token-exchange response; absence
    here just means the expiry was not reported).
    """
    if token is None:
        return False
    if token.expires_at is None:
        return True
    reference = now or datetime.now(UTC)
    expires = datetime.fromisoformat(token.expires_at)
    return expires > reference


# --- IO: one-shot loopback callback listener and code-for-token exchange ---


class _CallbackHandler(BaseHTTPRequestHandler):
    """Single-request handler that stores the callback query on the server instance."""

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        self.server.callback_query = urlsplit(self.path).query  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Authorization received. You can close this window.")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Silence default stderr access logging: the raw request line includes
        # the authorization code in the query string.
        pass


def capture_authorization_code(
    port: int,
    expected_state: str,
    *,
    timeout_seconds: int = 120,
    server_factory: Callable[[tuple[str, int], type], Any] = HTTPServer,
) -> str:
    """Run a one-shot loopback HTTP listener bound to 127.0.0.1 and return the code.

    Binds strictly to 127.0.0.1 (never 0.0.0.0), serves exactly one request,
    enforces a timeout, and validates `state` before returning the code.
    """
    server = server_factory(("127.0.0.1", port), _CallbackHandler)
    server.timeout = timeout_seconds
    server.callback_query = None
    try:
        server.handle_request()
    finally:
        server.server_close()
    if server.callback_query is None:
        raise TimeoutError("Timed out waiting for the AniList OAuth callback")
    params = parse_callback_params(server.callback_query)
    return validate_callback(params, expected_state)


def exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    *,
    timeout_seconds: int = 30,
    session: requests.Session | None = None,
) -> StoredToken:
    """Exchange an authorization code for an access token.

    The client secret and code are sent only in the POST body, never in the
    URL or headers, and never surface in any exception raised here.
    """
    active_session = session or requests.Session()
    response = active_session.post(
        TOKEN_URL,
        json={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=timeout_seconds,
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    return parse_token_response(payload, obtained_at=datetime.now(UTC).isoformat())


# --- Orchestration: full authorization-code flow, wired for the `anilist-auth` CLI ---


def run_auth_flow(
    settings: "Settings",
    database: "TrackingDatabase",
    *,
    browser_opener: Callable[[str], bool] | None = None,
    session: requests.Session | None = None,
    callback_timeout_seconds: int = 120,
) -> StoredToken:
    """Run the full OAuth2 authorization-code flow and persist the resulting token.

    Validates required config, builds the consent URL, opens the browser (or
    prints the URL if no browser is available), captures and validates the
    loopback callback, exchanges the code for a token, and stores it. Never
    prints or logs the client secret, authorization code, or access token.
    """
    settings.validate_anilist_push()
    redirect_uri = redirect_uri_for(settings.anilist_redirect_port)
    state = generate_state()
    auth_url = build_authorize_url(settings.anilist_client_id, redirect_uri, state)

    print("Open this URL to authorize Hobby-Anime with AniList:")
    print(auth_url)
    opener = browser_opener or webbrowser.open
    opener(auth_url)

    code = capture_authorization_code(
        settings.anilist_redirect_port, state, timeout_seconds=callback_timeout_seconds
    )
    token = exchange_code(
        settings.anilist_client_id,
        settings.anilist_client_secret,
        code,
        redirect_uri,
        timeout_seconds=settings.request_timeout_seconds,
        session=session,
    )
    database.save_token(token)
    return token
