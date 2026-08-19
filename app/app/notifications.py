"""Completion-notification delivery through a configurable SMTP transport."""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Any

from app.config import settings


def email_notifications_configured() -> bool:
    """Whether this deployment can actually deliver a completion email.

    The opt-in on the plan card promises a message when the Goal Report
    lands, and the only thing standing behind that promise is an SMTP
    transport an operator has to configure. Without one the durable task
    raises below, spends its retries, and fails where no scientist can see
    it -- so callers gate the opt-in on this instead of offering something
    the server has no way to send.
    """
    return bool(settings.smtp_host and settings.smtp_from_email)


def _send_smtp(recipient: str, subject: str, body: str) -> None:
    """Send one completion email using STARTTLS when credentials are set."""
    if not email_notifications_configured():
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


async def deliver_email(recipient: str, subject: str, body: str) -> None:
    """Send one message off the event loop.

    ``smtplib`` is blocking and this server's event loop also drives runs,
    so the send goes to a thread rather than stalling every other request
    for the length of an SMTP conversation.

    Raises:
        RuntimeError: When no SMTP transport is configured.
    """
    await asyncio.to_thread(_send_smtp, recipient, subject, body)


async def deliver_completion_notification(
    inputs: dict[str, Any],
) -> dict[str, str]:
    """Deliver one durable task's completion message off the event loop."""
    recipient = str(inputs["email"])
    run_id = str(inputs["run_id"])
    title = str(inputs.get("title") or "Goal Report")
    # Which tab the mail links to. Carried on the task rather than fixed
    # here: a discovery run's nav has no Ideas tab, so the one link in
    # the mail would land on a tab the run does not show. Defaulted for
    # rows enqueued before this existed.
    tab = str(inputs.get("tab") or "ideas")
    report_url = f"{settings.public_app_url.rstrip('/')}/runs/{run_id}/{tab}"
    await deliver_email(
        recipient,
        f"Your Co-Scientist Goal Report is ready: {title}",
        f"Your Goal Report is complete.\n\nOpen it: {report_url}\n",
    )
    return {"recipient": recipient, "status": "sent"}
