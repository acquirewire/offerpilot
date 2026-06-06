"""Email alerts via SendGrid or plain SMTP, selected by EMAIL_BACKEND.
Blocking I/O is offloaded to a thread to keep the event loop responsive."""
from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

import structlog

from ..config import Settings

log = structlog.get_logger()


class EmailNotifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.backend = settings.email_backend
        if self.backend == "sendgrid":
            self.enabled = bool(settings.sendgrid_key and settings.email_to)
        else:
            self.enabled = bool(
                settings.smtp_host and settings.smtp_user and settings.email_to
            )

    async def send(self, subject: str, body: str) -> None:
        if not self.enabled:
            log.warning("email.disabled", backend=self.backend)
            return
        try:
            if self.backend == "sendgrid":
                await asyncio.to_thread(self._send_sendgrid, subject, body)
            else:
                await asyncio.to_thread(self._send_smtp, subject, body)
            log.info("email.sent", backend=self.backend)
        except Exception as exc:  # noqa: BLE001 - alerting must not crash loop
            log.error("email.failed", backend=self.backend, error=str(exc))

    def _send_smtp(self, subject: str, body: str) -> None:
        s = self.settings
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = s.email_from or s.smtp_user
        msg["To"] = ", ".join(s.email_to)
        msg.set_content(body)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as server:
            server.starttls()
            server.login(s.smtp_user, s.smtp_password)
            server.send_message(msg)

    def _send_sendgrid(self, subject: str, body: str) -> None:
        # Imported lazily so SMTP-only users don't need the package installed.
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        s = self.settings
        message = Mail(
            from_email=s.email_from,
            to_emails=s.email_to,
            subject=subject,
            plain_text_content=body,
        )
        SendGridAPIClient(s.sendgrid_key).send(message)
