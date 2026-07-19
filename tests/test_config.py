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
