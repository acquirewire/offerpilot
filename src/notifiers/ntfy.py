"""ntfy.sh push notifications -> instant alert on your phone, free, no account.

You pick a secret topic name; the phone app subscribes to it and the bot POSTs
to it. Anyone who knows the topic name can read it, so the topic doubles as a
password -- keep it private.
"""
from __future__ import annotations

import re

import httpx
import structlog

from ..config import Settings

log = structlog.get_logger()


class NtfyNotifier:
    def __init__(self, settings: Settings):
        self.server = settings.ntfy_server.rstrip("/")
        self.topic = settings.ntfy_topic
        self.enabled = bool(self.topic)

    async def send(self, subject: str, body: str, click_url: str | None = None) -> None:
        if not self.enabled:
            log.warning("ntfy.disabled", reason="no NTFY_TOPIC set")
            return
        # ntfy headers must be plain ASCII with no leading/trailing whitespace
        # (the HTTP layer rejects otherwise). Drop non-ASCII (emoji, em-dash)
        # and collapse the gaps they leave behind.
        title = re.sub(
            r"\s+", " ", subject.encode("ascii", "ignore").decode()
        ).strip() or "Ticket drop"
        headers = {
            "Title": title,
            "Priority": "urgent",
            "Tags": "tickets",
        }
        if click_url:
            headers["Click"] = click_url
        url = f"{self.server}/{self.topic}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, content=body.encode("utf-8"),
                                         headers=headers)
                resp.raise_for_status()
            log.info("ntfy.sent", topic=self.topic)
        except Exception as exc:  # noqa: BLE001 - alerting must not crash loop
            log.error("ntfy.failed", error=str(exc))
