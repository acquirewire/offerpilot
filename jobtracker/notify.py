"""Alerting for the Drop Tracker (Module 1): ntfy push + optional email.

Reuses the same env vars as the Fatsoma bot (SMTP_HOST/SMTP_USER/ALERT_EMAIL_TO
...), so one .env drives both projects. Email is self-contained stdlib SMTP —
no coupling to src.config's Settings object. Both channels are best-effort:
a failure is logged, never raised, so the poll loop can't die on a bad alert.
"""
from __future__ import annotations

import asyncio
import os
import smtplib
from email.message import EmailMessage

import httpx
import structlog

log = structlog.get_logger()


async def alert(topic: str | None, title: str, body: str) -> None:
    """Fan out one alert to every configured channel concurrently."""
    await asyncio.gather(push(topic, title, body), email(title, body))


async def push(topic: str | None, title: str, body: str) -> None:
    """Fire a single ntfy notification. No-op (logged) if no topic configured."""
    if not topic:
        log.debug("notify.ntfy.disabled", reason="no ntfy_topic")
        return
    server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    try:
        # Publish via ntfy's JSON API (UTF-8 safe). Putting the title in an HTTP
        # header breaks on non-ASCII (emoji, "Société Générale", "L'Oréal").
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                server,
                json={
                    "topic": topic,
                    "title": title,
                    "message": body,
                    "priority": 4,
                    "tags": ["briefcase"],
                },
            )
        log.info("notify.ntfy.sent", title=title)
    except Exception as exc:  # noqa: BLE001 - alerting must not crash the loop
        log.error("notify.ntfy.failed", error=str(exc))


async def email(subject: str, body: str) -> None:
    """Send an email alert via SMTP if SMTP_HOST + ALERT_EMAIL_TO are set."""
    host = os.getenv("SMTP_HOST", "")
    to = [a.strip() for a in os.getenv("ALERT_EMAIL_TO", "").split(",") if a.strip()]
    if not (host and to):
        log.debug("notify.email.disabled", reason="SMTP_HOST/ALERT_EMAIL_TO unset")
        return
    try:
        await asyncio.to_thread(_send_smtp, host, to, subject, body)
        log.info("notify.email.sent", subject=subject)
    except Exception as exc:  # noqa: BLE001
        log.error("notify.email.failed", error=str(exc))


def _send_smtp(host: str, to: list[str], subject: str, body: str) -> None:
    user = os.getenv("SMTP_USER", "")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.getenv("ALERT_EMAIL_FROM", "") or user
    msg["To"] = ", ".join(to)
    msg.set_content(body)
    port = int(os.getenv("SMTP_PORT", "587") or "587")
    with smtplib.SMTP(host, port, timeout=20) as server:
        server.starttls()
        if user:
            server.login(user, os.getenv("SMTP_PASSWORD", ""))
        server.send_message(msg)
