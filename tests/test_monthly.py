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
