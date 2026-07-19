from dataclasses import replace

from hobby_anime.config import Settings
from hobby_anime.models import SeasonalMedia
from hobby_anime.monthly import run_monthly


class FakeAniList:
    def current_season(self) -> list[SeasonalMedia]:
        return [
            SeasonalMedia(
                1,
                "Seasonal Example",
                episodes=12,
                genres=("Adventure",),
                score=80,
                url="https://anilist.co/anime/1",
            )
        ]


class FakeNotifier:
    def __init__(self) -> None:
        self.report = ""

    def send(self, report: str) -> list[str]:
        self.report = report
        return ["test"]


class FakeRecommender:
    def generate(self, library: list[object], media: list[SeasonalMedia]) -> str:
        return "# AI report"


class FakeSonarr:
    def series(self) -> list[dict[str, object]]:
        return [
            {
                "title": "Owned Show",
                "path": "/data/media/anime/Owned Show",
                "statistics": {"episodeFileCount": 4},
            }
        ]

    def calendar(self, start: object, end: object) -> list[dict[str, object]]:
        return [
            {
                "title": "Episode 5",
                "airDateUtc": "2026-07-20T10:00:00Z",
                "series": {"title": "Owned Show"},
            }
        ]


class BrokenAniList:
    def current_season(self) -> list[SeasonalMedia]:
        raise RuntimeError("AniList unreachable")


class BrokenSonarr:
    def series(self) -> list[dict[str, object]]:
        raise RuntimeError("Sonarr unreachable")

    def calendar(self, start: object, end: object) -> list[dict[str, object]]:
        raise RuntimeError("Sonarr unreachable")


def test_monthly_survives_anilist_failure(settings: Settings) -> None:
    notifier = FakeNotifier()

    report = run_monthly(settings, anilist_client=BrokenAniList(), notifier=notifier)

    assert report
    assert notifier.report == report


def test_monthly_survives_sonarr_failure(settings: Settings) -> None:
    configured = replace(settings, sonarr_enabled=True, sonarr_api_key="secret")
    notifier = FakeNotifier()

    report = run_monthly(
        configured,
        anilist_client=FakeAniList(),
        notifier=notifier,
        sonarr_client=BrokenSonarr(),
    )

    assert "Seasonal Example" in report
    assert notifier.report == report


def test_monthly_uses_deterministic_report_by_default(settings: Settings) -> None:
    notifier = FakeNotifier()

    report = run_monthly(settings, anilist_client=FakeAniList(), notifier=notifier)

    assert "Seasonal Example" in report
    assert notifier.report == report


def test_monthly_uses_local_recommender_when_enabled(settings: Settings) -> None:
    notifier = FakeNotifier()
    enabled_settings = replace(settings, ollama_enabled=True)

    report = run_monthly(
        enabled_settings,
        anilist_client=FakeAniList(),
        notifier=notifier,
        recommender=FakeRecommender(),
    )

    assert report == "# AI report"
    assert notifier.report == report


def test_monthly_includes_sonarr_catalog_and_calendar(settings: Settings) -> None:
    configured = replace(
        settings,
        sonarr_enabled=True,
        sonarr_api_key="secret",
    )

    report = run_monthly(
        configured,
        anilist_client=FakeAniList(),
        notifier=FakeNotifier(),
        sonarr_client=FakeSonarr(),
    )

    assert "Títulos locales detectados: 1" in report
    assert "Próximos episodios (Sonarr)" in report
    assert "Owned Show: Episode 5" in report
