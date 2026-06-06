"""Fans one alert out to every channel concurrently."""
from __future__ import annotations

import asyncio

from ..config import Settings
from .email import EmailNotifier
from .ntfy import NtfyNotifier


class NotificationDispatcher:
    def __init__(self, settings: Settings):
        self._channels = [
            NtfyNotifier(settings),
            EmailNotifier(settings),
            # SMS disabled: Twilio's free trial can't text UK numbers. Re-add
            # SmsNotifier(settings) here if you upgrade the Twilio account.
        ]

    async def alert(self, subject: str, body: str) -> None:
        await asyncio.gather(
            *(c.send(subject, body) for c in self._channels)
        )
