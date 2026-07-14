from __future__ import annotations

import logging

import requests

LOGGER = logging.getLogger(__name__)


class Notifier:
    def __init__(
        self,
        webhook_url: str = "",
        telegram_bot_token: str = "",
        telegram_chat_id: str = "",
        timeout_seconds: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        self.webhook_url = webhook_url
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def send(self, report: str) -> list[str]:
        delivered_to: list[str] = []
        if self.webhook_url:
            response = self.session.post(
                self.webhook_url,
                json={"text": report},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            delivered_to.append("webhook")

        if self.telegram_bot_token and self.telegram_chat_id:
            for part in _split_message(report):
                response = self.session.post(
                    f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage",
                    json={"chat_id": self.telegram_chat_id, "text": part},
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
            delivered_to.append("telegram")

        if not delivered_to:
            LOGGER.info("No notification channel configured; report written to logs")
            LOGGER.info("\n%s", report)
        return delivered_to


def _split_message(message: str, limit: int = 4_000) -> list[str]:
    if len(message) <= limit:
        return [message]
    parts: list[str] = []
    remaining = message
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        boundary = remaining.rfind("\n", 0, limit)
        if boundary <= 0:
            boundary = limit
        parts.append(remaining[:boundary])
        remaining = remaining[boundary:].lstrip("\n")
    return parts
