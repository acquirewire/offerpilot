"""Twilio SMS alerts. Runs the blocking SDK call in a thread so it never
stalls the asyncio polling loop."""
from __future__ import annotations

import asyncio

import structlog

from ..config import Settings

log = structlog.get_logger()


class SmsNotifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.enabled = bool(
            settings.twilio_sid and settings.twilio_token and settings.sms_to
        )
        # twilio imported lazily so the package works without it installed
        # (HTTP-only deployments that use ntfy/email don't need it).
        if self.enabled:
            from twilio.rest import Client

            self._client = Client(settings.twilio_sid, settings.twilio_token)
        else:
            self._client = None

    async def send(self, subject: str, body: str) -> None:
        if not self.enabled:
            log.warning("sms.disabled", reason="missing twilio config")
            return
        text = f"{subject}\n{body}"[:1500]  # keep SMS short
        for to in self.settings.sms_to:
            try:
                await asyncio.to_thread(
                    self._client.messages.create,
                    body=text,
                    from_=self.settings.twilio_from,
                    to=to,
                )
                log.info("sms.sent", to=to)
            except Exception as exc:  # noqa: BLE001 - alerting must not crash loop
                log.error("sms.failed", to=to, error=str(exc))
