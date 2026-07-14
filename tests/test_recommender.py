from pathlib import Path

from hobby_anime.models import LibraryItem, SeasonalMedia
from hobby_anime.recommender import build_fallback_report, mark_library_matches


def test_matches_alternative_title_and_reports_missing_episodes() -> None:
    library = [LibraryItem("My Hero Academia", Path("/media/mha"), 10, 10)]
    media = [
        SeasonalMedia(
            1,
            "Boku no Hero Academia",
            alternative_titles=("My Hero Academia",),
            episodes=12,
            score=80,
            url="https://anilist.co/anime/1",
        ),
        SeasonalMedia(
            2,
            "New Show",
            episodes=12,
            genres=("Comedy",),
            score=90,
            url="https://anilist.co/anime/2",
        ),
    ]

    matched = mark_library_matches(library, media)
    report = build_fallback_report(library, matched)

    assert matched[0].in_library is True
    assert matched[1].in_library is False
    assert "local hasta 10" in report
    assert "New Show" in report
