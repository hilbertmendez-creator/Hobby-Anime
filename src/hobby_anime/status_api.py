"""Read-only JSON status/health HTTP API for the hobby-anime pipeline.

Exposes ``GET /status`` (pipeline counts) and ``GET /health`` (dependency
diagnostics) behind a static header token, documented via FastAPI's
runtime OpenAPI 3.1 generation (``/openapi.json``, ``/docs``).

Run with uvicorn's application factory support:

    uvicorn hobby_anime.status_api:build_app --factory --host 0.0.0.0 --port 8787
"""

from __future__ import annotations

import hmac
from typing import Any, Protocol

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, RootModel

from hobby_anime import doctor
from hobby_anime.config import Settings
from hobby_anime.database import TrackingDatabase

_TOKEN_HEADER = APIKeyHeader(
    name="X-API-Token",
    auto_error=False,
    description="Static API token configured via the STATUS_API_TOKEN environment variable.",
)


class PipelineDatabase(Protocol):
    """Minimal contract this module needs from a tracking database."""

    def pipeline_summary(self) -> dict[str, dict[str, int]]: ...


class PipelineSummary(RootModel[dict[str, dict[str, int]]]):
    """Pipeline status counts keyed by stage (`rss`, `verification`, `import`)."""

    model_config = {
        "json_schema_extra": {
            "example": {
                "rss": {"added": 12, "error": 1},
                "verification": {"processing": 2, "verified": 8, "rejected": 1},
                "import": {"pending": 1, "imported": 7},
            }
        }
    }


class CheckResult(BaseModel):
    """A single diagnostic check outcome."""

    ok: bool
    detail: str


class HealthReport(RootModel[dict[str, CheckResult]]):
    """Diagnostic check results keyed by check name."""

    model_config = {
        "json_schema_extra": {
            "example": {
                "database": {"ok": True, "detail": "/config/hobby-anime.db"},
                "qbittorrent": {"ok": False, "detail": "Connection refused"},
            }
        }
    }


_UNAUTHORIZED_RESPONSE = {
    "description": "Missing or invalid API token",
    "content": {"application/json": {"example": {"detail": "Invalid or missing API token"}}},
}


def create_app(settings: Settings, database: PipelineDatabase) -> FastAPI:
    """Build the FastAPI app, injecting settings and a database dependency.

    This factory is the test seam: tests pass a fake database and a
    `Settings` instance with a known token via `TestClient(create_app(...))`.
    """
    app = FastAPI(
        title="Hobby-Anime Status API",
        version="1.0.0",
        description=(
            "Read-only JSON status and health endpoints for the hobby-anime "
            "media pipeline. Every route requires the `X-API-Token` header."
        ),
    )

    def require_token(token: str | None = Depends(_TOKEN_HEADER)) -> None:
        if (
            not settings.status_api_token
            or not token
            or not hmac.compare_digest(token, settings.status_api_token)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API token",
            )

    @app.get(
        "/status",
        response_model=PipelineSummary,
        summary="Pipeline status counts",
        description="Returns per-stage status counts from the tracking database.",
        responses={401: _UNAUTHORIZED_RESPONSE},
        dependencies=[Depends(require_token)],
    )
    def get_status() -> dict[str, dict[str, int]]:
        return database.pipeline_summary()

    @app.get(
        "/health",
        response_model=HealthReport,
        summary="System health checks",
        description=(
            "Returns diagnostic checks for storage, media, and third-party "
            "dependencies. Always returns 200; degraded checks are reported "
            "in the payload via `ok: false`."
        ),
        responses={401: _UNAUTHORIZED_RESPONSE},
        dependencies=[Depends(require_token)],
    )
    def get_health() -> dict[str, dict[str, Any]]:
        return doctor.run_checks(settings)

    return app


def build_app() -> FastAPI:
    """Construct the production app from environment settings.

    Fails closed: raises `RuntimeError` before serving any request if
    `STATUS_API_TOKEN` is unset or empty, so the process cannot start in
    an unauthenticated state.
    """
    settings = Settings.from_env()
    if not settings.status_api_token:
        raise RuntimeError(
            "STATUS_API_TOKEN must be set to a non-empty value to start the status API"
        )
    database = TrackingDatabase(settings.database_path)
    database.initialize()
    return create_app(settings, database)
