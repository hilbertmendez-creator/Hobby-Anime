from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from hobby_anime.config import Settings


class FakeDatabase:
    def __init__(self, summary: dict[str, dict[str, int]]) -> None:
        self._summary = summary

    def pipeline_summary(self) -> dict[str, dict[str, int]]:
        return self._summary


@pytest.fixture
def api_settings(settings: Settings) -> Settings:
    return replace(settings, status_api_token="secret-token")


def test_build_app_raises_when_token_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    from hobby_anime import status_api

    monkeypatch.delenv("STATUS_API_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="STATUS_API_TOKEN"):
        status_api.build_app()


def test_status_requires_token_header(api_settings: Settings) -> None:
    from hobby_anime import status_api

    app = status_api.create_app(api_settings, FakeDatabase({"rss": {"added": 1}}))
    client = TestClient(app)

    response = client.get("/status")

    assert response.status_code == 401


def test_status_rejects_wrong_token(api_settings: Settings) -> None:
    from hobby_anime import status_api

    app = status_api.create_app(api_settings, FakeDatabase({"rss": {"added": 1}}))
    client = TestClient(app)

    response = client.get("/status", headers={"X-API-Token": "wrong"})

    assert response.status_code == 401


def test_status_returns_pipeline_summary_with_valid_token(api_settings: Settings) -> None:
    from hobby_anime import status_api

    summary = {
        "rss": {"added": 3, "error": 1},
        "verification": {"processing": 2, "verified": 5},
        "import": {"pending": 1},
    }
    app = status_api.create_app(api_settings, FakeDatabase(summary))
    client = TestClient(app)

    response = client.get("/status", headers={"X-API-Token": "secret-token"})

    assert response.status_code == 200
    assert response.json() == summary


def test_health_returns_run_checks_result_with_degraded_entry(
    api_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hobby_anime import status_api

    fake_result = {
        "database": {"ok": True, "detail": str(api_settings.database_path)},
        "qbittorrent": {"ok": False, "detail": "Connection refused"},
    }
    monkeypatch.setattr(status_api.doctor, "run_checks", lambda settings: fake_result)

    app = status_api.create_app(api_settings, FakeDatabase({}))
    client = TestClient(app)

    response = client.get("/health", headers={"X-API-Token": "secret-token"})

    assert response.status_code == 200
    assert response.json() == fake_result


def test_health_requires_token(api_settings: Settings) -> None:
    from hobby_anime import status_api

    app = status_api.create_app(api_settings, FakeDatabase({}))
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 401


def test_openapi_documents_routes_and_auth_scheme(api_settings: Settings) -> None:
    from hobby_anime import status_api

    app = status_api.create_app(api_settings, FakeDatabase({}))
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    document = response.json()
    assert document["openapi"].startswith("3.1")
    assert "/status" in document["paths"]
    assert "/health" in document["paths"]
    for path in ("/status", "/health"):
        responses = document["paths"][path]["get"]["responses"]
        assert "200" in responses
        assert "401" in responses
    security_schemes = document["components"]["securitySchemes"]
    assert any(
        scheme.get("type") == "apiKey" and scheme.get("name") == "X-API-Token"
        for scheme in security_schemes.values()
    )
