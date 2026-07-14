import pytest

from hobby_anime.config import Settings


def test_invalid_boolean_cannot_disable_spanish_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPANISH_ONLY", "treu")

    with pytest.raises(ValueError, match="SPANISH_ONLY must be a boolean"):
        Settings.from_env()
