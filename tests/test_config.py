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
