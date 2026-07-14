from pathlib import Path

from hobby_anime.library import audit_library, extract_episode, normalize_title


def test_audit_library_groups_files_and_detects_latest_episode(tmp_path: Path) -> None:
    media_path = tmp_path / "media"
    series_path = media_path / "Example Show"
    series_path.mkdir(parents=True)
    (series_path / "Example Show - 01 [1080p].mkv").touch()
    (series_path / "Example Show S01E03.mp4").touch()
    (series_path / "poster.jpg").touch()

    result = audit_library(media_path)

    assert len(result) == 1
    assert result[0].title == "Example Show"
    assert result[0].file_count == 2
    assert result[0].latest_episode == 3


def test_episode_and_title_normalization() -> None:
    assert extract_episode("A Show - 12v2 [1080p]") == 12
    assert normalize_title("Pokémon: Élite!") == "pokemon elite"
