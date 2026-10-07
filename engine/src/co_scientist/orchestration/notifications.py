from __future__ import annotations

import asyncio
import smtplib
import sqlite3
import ssl
from email.message import EmailMessage
from typing import Any

from co_scientist.core.config import settings


def email_notifications_configured() -> bool:
    # SMTP credentials do not establish recipient consent or delivery admission.
    # Keep the public opt-in unavailable until both exist.
    return False


def _send_smtp(recipient: str, subject: str, body: str) -> None:
    if not (settings.smtp_host and settings.smtp_from_email):
        raise RuntimeError("SMTP completion notifications are not configured")
    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    if settings.smtp_ca_bundle:
        context.load_verify_locations(cafile=settings.smtp_ca_bundle)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls(context=context)
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


async def deliver_email(recipient: str, subject: str, body: str) -> None:
    """SMTP is blocking; send off-loop so mail cannot stall API requests or
    worker progress.
    """
    await asyncio.to_thread(_send_smtp, recipient, subject, body)


async def deliver_completion_notification(
    inputs: dict[str, Any],
) -> dict[str, str]:
    # Old durable tasks contain unverified recipients too; finish without
    # SMTP I/O so restart/retry cannot revive anonymous mail delivery.
    return {"status": "disabled"}


def enqueue_completion_notification(
    run_id: str,
    research_goal: str,
    report_id: str,
    *,
    db_path: str | None,
    conn: sqlite3.Connection | None = None,
) -> None:
    # Preserve legacy callers/configuration without authorizing public mail.
    return
