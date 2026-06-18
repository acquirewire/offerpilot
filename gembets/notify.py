"""Alerting: ntfy push + optional email. Same env vars as the jobtracker/Fatsoma/
boostmatcher bots (NTFY_SERVER, SMTP_HOST/SMTP_USER/SMTP_PASSWORD, ALERT_EMAIL_TO/
FROM), so one .env drives every project. Both channels are best-effort — a failure
is logged, never raised, so the poll loop can't die on a bad alert.
"""
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
from email.message import EmailMessage

import httpx

log = logging.getLogger(__name__)


async def alert(topic: str | None, title: str, body: str, *, priority: int = 4) -> None:
    await asyncio.gather(push(topic, title, body, priority=priority), email(title, body))


async def push(topic: str | None, title: str, body: str, *, priority: int = 4) -> None:
    if not topic:
        return
    server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    try:
        # JSON API (not HTTP headers) so emoji + accented fixture names survive.
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(server, json={"topic": topic, "title": title, "message": body,
                                            "priority": priority,
                                            "tags": ["gem_stone", "soccer"]})
    except Exception as exc:  # noqa: BLE001 — alerting must not crash the loop
        log.error("ntfy failed: %s", exc)


async def email(subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST", "")
    to = [a.strip() for a in os.getenv("ALERT_EMAIL_TO", "").split(",") if a.strip()]
    if not (host and to):
        return
    try:
        await asyncio.to_thread(_send_smtp, host, to, subject, body)
    except Exception as exc:  # noqa: BLE001
        log.error("email failed: %s", exc)


def _send_smtp(host: str, to: list[str], subject: str, body: str) -> None:
    user = os.getenv("SMTP_USER", "")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.getenv("ALERT_EMAIL_FROM", "") or user
    msg["To"] = ", ".join(to)
    msg.set_content(body)
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587") or "587"), timeout=20) as s:
        s.starttls()
        if user:
            s.login(user, os.getenv("SMTP_PASSWORD", ""))
        s.send_message(msg)
