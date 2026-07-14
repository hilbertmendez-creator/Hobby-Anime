from hobby_anime.notifications import Notifier


class FakeResponse:
    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        return FakeResponse()


def test_notifier_delivers_to_webhook_and_telegram() -> None:
    session = FakeSession()
    notifier = Notifier(
        webhook_url="https://hooks.example.test/report",
        telegram_bot_token="token",
        telegram_chat_id="chat",
        session=session,
    )

    result = notifier.send("Monthly report")

    assert result == ["webhook", "telegram"]
    assert session.calls[0][1]["json"] == {"text": "Monthly report"}
    assert session.calls[1][0].endswith("/bottoken/sendMessage")
