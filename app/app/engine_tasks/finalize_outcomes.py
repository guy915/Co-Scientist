"""Replay and settlement outcomes for durable report finalization."""

from __future__ import annotations

from typing import Any

from app import store
from app.engine_tasks.support import SafetyHoldError
from app.store import RunStatus


def _finalize_replay_or_none(
    run: store.RunRow, *, db_path: str | None
) -> dict[str, Any] | None:
    """Return the replayed outcome when finalization already published."""
    if run.status == RunStatus.CANCELLED.value:
        raise RuntimeError("run cancelled before finalization")
    already_published = (
        run.status == RunStatus.COMPLETED.value
        and store.get_latest_report(run.id, db_path=db_path) is not None
    )
    if already_published:
        return {"run_id": run.id, "status": "completed", "replayed": True}
    return None


def _settle_finalize_outcome(
    run_id: str, db_path: str | None
) -> dict[str, Any]:
    """Report outcome; park unpublished work for explicit resume."""
    run = store.get_run(run_id, db_path=db_path)
    status = run.status if run else "missing"
    if (
        status == RunStatus.PAUSED.value
        and store.get_latest_report(run_id, db_path=db_path) is None
    ):
        raise SafetyHoldError("report finalization held for review")
    return {"run_id": run_id, "status": status}
