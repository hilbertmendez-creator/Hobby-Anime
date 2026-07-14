from datetime import date

from hobby_anime.anilist import AniListClient


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "data": {
                "Page": {
                    "pageInfo": {"hasNextPage": False},
                    "media": [
                        {
                            "id": 123,
                            "title": {
                                "romaji": "Example Anime",
                                "english": "Example Show",
                                "native": "例",
                            },
                            "episodes": 12,
                            "genres": ["Adventure"],
                            "averageScore": 82,
                            "description": "A <b>safe</b> synopsis.",
                            "siteUrl": "https://anilist.co/anime/123",
                        }
                    ],
                }
            }
        }


class FakeSession:
    def __init__(self) -> None:
        self.payload: dict[str, object] = {}

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.payload = kwargs["json"]
        return FakeResponse()


def test_current_season_maps_response() -> None:
    session = FakeSession()
    client = AniListClient(session=session)

    result = client.current_season(date(2026, 7, 14))

    variables = session.payload["variables"]
    assert isinstance(variables, dict)
    assert variables["season"] == "SUMMER"
    assert result[0].title == "Example Anime"
    assert result[0].alternative_titles == ("Example Show", "例")
    assert result[0].description == "A safe synopsis."
