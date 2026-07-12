"""Completion-notification delivery through a configurable SMTP transport."""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Any

from app.config import settings


def _send_smtp(recipient: str, subject: str, body: str) -> None:
    """Send one completion email using STARTTLS when credentials are set."""
    if not settings.smtp_host or not settings.smtp_from_email:
        raise RuntimeError("SMTP completion notifications are not configured")
    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=15
    ) as smtp:
        smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


async def deliver_completion_notification(
    inputs: dict[str, Any],
) -> dict[str, str]:
    """Deliver one durable task's completion message off the event loop."""
    recipient = str(inputs["email"])
    run_id = str(inputs["run_id"])
    title = str(inputs.get("title") or "Goal Report")
    report_url = f"{settings.public_app_url.rstrip('/')}/runs/{run_id}/ideas"
    await asyncio.to_thread(
        _send_smtp,
        recipient,
        f"Your Co-Scientist Goal Report is ready: {title}",
        f"Your Goal Report is complete.\n\nOpen it: {report_url}\n",
    )
    return {"recipient": recipient, "status": "sent"}
