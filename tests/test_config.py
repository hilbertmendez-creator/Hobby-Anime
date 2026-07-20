from dataclasses import replace

import pytest

from hobby_anime.config import Settings


def test_invalid_boolean_cannot_disable_spanish_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPANISH_ONLY", "treu")

    with pytest.raises(ValueError, match="SPANISH_ONLY must be a boolean"):
        Settings.from_env()


def test_enabled_arr_services_require_api_keys(settings: Settings) -> None:
    with pytest.raises(ValueError, match="SONARR_API_KEY"):
        replace(settings, sonarr_enabled=True, sonarr_api_key="").validate_schedule()
    with pytest.raises(ValueError, match="PROWLARR_API_KEY"):
        replace(
            settings,
            prowlarr_enabled=True,
            prowlarr_api_key="",
        ).validate_schedule()
    with pytest.raises(ValueError, match="BAZARR_API_KEY"):
        replace(settings, bazarr_enabled=True, bazarr_api_key="").validate_schedule()


def test_settings_from_env_reads_jellyfin_watched_status_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JELLYFIN_API_KEY", "top-secret-key")
    monkeypatch.setenv("JELLYFIN_USER_ID", "user-123")
    monkeypatch.setenv("JELLYFIN_LIBRARY_ID", "lib-1")

    settings = Settings.from_env()

    assert settings.jellyfin_api_key == "top-secret-key"
    assert settings.jellyfin_user_id == "user-123"
    assert settings.jellyfin_library_id == "lib-1"


def test_settings_from_env_defaults_jellyfin_watched_status_vars_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JELLYFIN_API_KEY", raising=False)
    monkeypatch.delenv("JELLYFIN_USER_ID", raising=False)
    monkeypatch.delenv("JELLYFIN_LIBRARY_ID", raising=False)

    settings = Settings.from_env()

    assert settings.jellyfin_api_key == ""
    assert settings.jellyfin_user_id == ""
    assert settings.jellyfin_library_id == ""


def test_validate_schedule_requires_user_id_when_api_key_set(
    settings: Settings,
) -> None:
    with pytest.raises(ValueError, match="JELLYFIN_USER_ID"):
        replace(
            settings,
            jellyfin_api_key="top-secret-key",
            jellyfin_user_id="",
        ).validate_schedule()


def test_validate_schedule_error_never_leaks_jellyfin_api_key(
    settings: Settings,
) -> None:
    with pytest.raises(ValueError) as exc_info:
        replace(
            settings,
            jellyfin_api_key="top-secret-key",
            jellyfin_user_id="",
        ).validate_schedule()

    assert "top-secret-key" not in str(exc_info.value)
    assert "top-secret-key" not in repr(exc_info.value)


def test_settings_from_env_reads_anilist_push_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANILIST_CLIENT_ID", "client-123")
    monkeypatch.setenv("ANILIST_CLIENT_SECRET", "super-secret-value")
    monkeypatch.setenv("ANILIST_REDIRECT_PORT", "9999")

    settings = Settings.from_env()

    assert settings.anilist_client_id == "client-123"
    assert settings.anilist_client_secret == "super-secret-value"
    assert settings.anilist_redirect_port == 9999


def test_settings_from_env_defaults_anilist_redirect_port_distinct_from_status_api_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANILIST_REDIRECT_PORT", raising=False)
    monkeypatch.delenv("STATUS_API_PORT", raising=False)

    settings = Settings.from_env()

    assert settings.anilist_redirect_port == 8712
    assert settings.anilist_redirect_port != settings.status_api_port


def test_validate_anilist_push_requires_client_id_and_secret(
    settings: Settings,
) -> None:
    with pytest.raises(ValueError, match="ANILIST_CLIENT_ID"):
        replace(
            settings,
            anilist_client_id="",
            anilist_client_secret="",
        ).validate_anilist_push()

    with pytest.raises(ValueError, match="ANILIST_CLIENT_SECRET"):
        replace(
            settings,
            anilist_client_id="client-123",
            anilist_client_secret="",
        ).validate_anilist_push()


def test_validate_anilist_push_rejects_redirect_port_collision(
    settings: Settings,
) -> None:
    with pytest.raises(ValueError, match="ANILIST_REDIRECT_PORT"):
        replace(
            settings,
            anilist_client_id="client-123",
            anilist_client_secret="super-secret-value",
            anilist_redirect_port=settings.status_api_port,
        ).validate_anilist_push()


def test_validate_anilist_push_error_never_leaks_client_secret(
    settings: Settings,
) -> None:
    with pytest.raises(ValueError) as exc_info:
        replace(
            settings,
            anilist_client_id="",
            anilist_client_secret="super-secret-value",
        ).validate_anilist_push()

    assert "super-secret-value" not in str(exc_info.value)
    assert "super-secret-value" not in repr(exc_info.value)
