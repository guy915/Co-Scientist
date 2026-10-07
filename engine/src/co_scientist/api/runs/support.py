"""Existence guards live below routers to avoid sibling/router import cycles."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from co_scientist.core.exceptions import ContinuationAdmissionError
from co_scientist.domains.chat.repository import messages
from co_scientist.domains.chat.repository.messages import NewMessage
from co_scientist.orchestration.repository import runs
from co_scientist.platform.db import Connection
from co_scientist.platform.db.models import RunRow, ScientificTask


def _run_or_404(run_id: str, conn: Connection | None = None) -> RunRow:
    run = runs.get_run(run_id, conn=conn)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


def _require_run(run_id: str) -> None:
    if not runs.run_exists(run_id):
        raise HTTPException(status_code=404, detail="run not found")


def _steer_and_continue(
    run_id: str,
    sender: str,
    content: str,
    meta: dict[str, Any],
) -> ScientificTask | None:
    """Contributions continue from durable checkpoint state rather than
    restarting prior scientific work.
    """
    message = messages.append_message(
        NewMessage(
            run_id=run_id,
            sender=sender,
            content=content,
            kind="steering",
            meta=meta,
        )
    )
    return request_continuation(run_id, message.id)


def request_continuation(run_id: str, input_id: int) -> ScientificTask | None:
    from co_scientist.orchestration import engine_tasks

    try:
        return engine_tasks.enqueue_scientist_continuation(run_id, input_id)
    except ContinuationAdmissionError as exc:
        raise HTTPException(status_code=409 if exc.capacity else 429, detail=str(exc)) from exc
