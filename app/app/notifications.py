from __future__ import annotations

import asyncio
import logging
import smtplib
import sqlite3
import ssl
from email.message import EmailMessage
from typing import Any

from co_scientist.core.config import settings

from app.store import runs, tasks
from app.store.tasks import NewTask

logger = logging.getLogger(__name__)


def email_notifications_configured() -> bool:
    """Offer completion-email opt-in only when SMTP can fulfill it, rather
    than exhausting invisible delivery retries.
    """
    return bool(settings.smtp_host and settings.smtp_from_email)


def _send_smtp(recipient: str, subject: str, body: str) -> None:
    if not email_notifications_configured():
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
    recipient = str(inputs["email"])
    run_id = str(inputs["run_id"])
    title = str(inputs.get("title") or "Goal Report")
    # Discovery runs have no Ideas tab; honor the task's target while legacy
    # notification rows keep their default.
    tab = str(inputs.get("tab") or "ideas")
    report_url = f"{settings.public_app_url.rstrip('/')}/runs/{run_id}/{tab}"
    await deliver_email(
        recipient,
        f"Your Co-Scientist Goal Report is ready: {title}",
        f"Your Goal Report is complete.\n\nOpen it: {report_url}\n",
    )
    return {"recipient": recipient, "status": "sent"}


def _enqueue_completion_notification(
    run_id: str,
    research_goal: str,
    report_id: str,
    *,
    db_path: str | None,
    conn: sqlite3.Connection | None = None,
) -> None:
    run = runs.get_run(run_id, db_path=db_path, conn=conn)
    notification = (run.config.get("completion_notification") if run else {}) or {}
    if not (notification.get("enabled") and notification.get("email")):
        return
    if not email_notifications_configured():
        # Do not spend notification retries on SMTP that disappeared mid-run.
        logger.warning(
            "Run %s opted into a completion email but SMTP is not "
            "configured (set SMTP_HOST and SMTP_FROM_EMAIL); no mail sent",
            run_id,
        )
        return
    tasks.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type="notification.email",
            inputs={
                "run_id": run_id,
                "email": notification["email"],
                "title": run.title or research_goal if run else research_goal,
                "tab": "ideas",
            },
            idempotency_key=f"completion-email:{report_id}",
            priority=-100,
            dependencies=(),
            provenance={"trigger": "Goal Report completed"},
            budget={"delivery_attempts": 3},
            max_attempts=3,
        ),
        db_path=db_path,
        conn=conn,
    )
