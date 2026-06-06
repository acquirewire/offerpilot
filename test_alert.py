"""One-off check: fire a test SMS + email using the saved .env credentials.

Run:  .venv/Scripts/python.exe test_alert.py
It prints a clear PASS/FAIL per channel with the underlying error if any.
"""
from __future__ import annotations

import asyncio

from src import config as config_mod
from src.notifiers.email import EmailNotifier
from src.notifiers.sms import SmsNotifier


async def main() -> None:
    settings = config_mod.load()

    subject = "TEST: Ticket monitor alert"
    body = "If you can read this, your alerts are wired up correctly."

    print("\n--- SMS (Twilio) ---")
    sms = SmsNotifier(settings)
    if not sms.enabled:
        print("FAIL: SMS not configured (check TWILIO_* and ALERT_SMS_TO in .env)")
    else:
        try:
            for to in settings.sms_to:
                msg = await asyncio.to_thread(
                    sms._client.messages.create,
                    body=f"{subject}\n{body}",
                    from_=settings.twilio_from,
                    to=to,
                )
                print(f"PASS: SMS queued to {to}  (sid={msg.sid}, status={msg.status})")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: SMS error -> {exc}")

    print("\n--- Email ---")
    email = EmailNotifier(settings)
    if not email.enabled:
        print("FAIL: Email not configured (check SMTP_* / EMAIL_* in .env)")
    else:
        try:
            if email.backend == "sendgrid":
                await asyncio.to_thread(email._send_sendgrid, subject, body)
            else:
                await asyncio.to_thread(email._send_smtp, subject, body)
            print(f"PASS: Email sent via {email.backend} to {settings.email_to}")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: Email error -> {exc}")

    print()


if __name__ == "__main__":
    asyncio.run(main())
