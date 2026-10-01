"""Completion-email scheduling for a released Goal Report.

Split from ``app.report_render``, which re-exports the names callers use so
they keep a single import surface. Kept separate because deciding whether a
scientist gets mailed is a distinct concern from building, gating, and
publishing the report itself -- and the only part of that pipeline that
depends on the SMTP configuration.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from app import store
from app.notifications import email_notifications_configured

logger = logging.getLogger(__name__)


def _completion_email_deliverable(
    run_id: str, notification: dict[str, Any]
) -> bool:
    """Report whether a completion email both was asked for and can be sent.

    Args:
        run_id: Identifier of the run that finished.
        notification: The run's ``completion_notification`` config.

    Returns:
        True when the run opted in and SMTP is configured to deliver.
    """
    if not (notification.get("enabled") and notification.get("email")):
        return False
    if not email_notifications_configured():
        # Enqueueing here would spend three retries against an SMTP transport
        # that provably does not exist and leave a failed task nothing
        # recovers, all of it invisible to the scientist who asked to be
        # told. The opt-in is gated on the same capability in the UI, so
        # reaching this means the server lost its configuration mid-run.
        logger.warning(
            "Run %s opted into a completion email but SMTP is not "
            "configured (set SMTP_HOST and SMTP_FROM_EMAIL); no mail sent",
            run_id,
        )
        return False
    return True


def _completion_email_task(
    run_id: str,
    title: str,
    email: str,
    report_id: str,
) -> store.NewTask:
    """Build the durable task that mails one run's completion notice.

    Args:
        run_id: Identifier of the run that finished.
        title: Subject line material -- the run's title or its goal.
        email: Address the scientist asked to be notified at.
        report_id: Identifier of the published report, keying the task.

    Returns:
        The task row to enqueue.
    """
    return store.NewTask(
        run_id=run_id,
        task_type="notification.email",
        inputs={
            "run_id": run_id,
            "email": email,
            "title": title,
            "tab": "ideas",
        },
        idempotency_key=f"completion-email:{report_id}",
        priority=-100,
        dependencies=(),
        provenance={"trigger": "Goal Report completed"},
        budget={"delivery_attempts": 3},
        max_attempts=3,
    )


def _enqueue_completion_notification(
    run_id: str,
    research_goal: str,
    report_id: str,
    *,
    db_path: str | None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Enqueue the completion email task when the run opted in."""
    run = store.get_run(run_id, db_path=db_path, conn=conn)
    notification = (
        run.config.get("completion_notification") if run else {}
    ) or {}
    if not _completion_email_deliverable(run_id, notification):
        return
    store.enqueue_task(
        _completion_email_task(
            run_id,
            run.title or research_goal if run else research_goal,
            notification["email"],
            report_id,
        ),
        db_path=db_path,
        conn=conn,
    )
