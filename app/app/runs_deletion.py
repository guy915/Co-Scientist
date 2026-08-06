"""Permanent run deletion: ``DELETE /api/runs/{run_id}``.

Split out of ``app.runs`` (which re-exports and mounts this router, so the
served route set is unchanged) for the same reason ``runs_lifecycle`` and
``runs_contrib`` are split out: one concern per module. Addresses N3 (no
run/report/document deletion) for the run/report half; the document half
is ``DELETE /api/documents/{document_id}`` in ``app.documents``.

Ownership is enforced twice, deliberately: ``app.main.enforce_run_ownership``
already 404s a request that names another client's run before it reaches
here, and ``_run_or_404`` repeats the same guard so this module's behavior
does not depend on the middleware staying wired up exactly this way.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app import store
from app.runs_support import _run_or_404
from app.store import RunRow

router = APIRouter()

# Statuses with a live or claimable worker lease. Everything else -- draft
# (never started), paused (its task is parked, not leased), and every
# terminal status -- has no in-flight writer to race, so deletion is safe.
# Mirrors the frontend's ACTIVE_STATUSES (see api/runs.ts::isActiveStatus).
_ACTIVE_STATUSES = frozenset({"queued", "running", "synthesizing"})


def _guard_deletable(run: RunRow) -> None:
    """Raise 403/409 when ``run`` cannot be permanently deleted yet.

    Raises:
        HTTPException: 403 for the shared demo run (a public fixture, not
            any one caller's data to remove); 409 when the run still has
            an active or resumable workflow, so a worker holding a lease
            never writes a child row for a run id that no longer exists.
    """
    if run.client_id == store.DEMO_CLIENT_ID:
        raise HTTPException(
            status_code=403, detail="the demo run cannot be deleted"
        )
    if run.status in _ACTIVE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="cancel the run before deleting it",
        )


@router.delete("/{run_id}")
async def delete_run(run_id: str) -> dict[str, Any]:
    """Permanently delete a run and every row scoped to it.

    The run must not be queued, running, or synthesizing -- an active run
    is cancelled first, through the existing cancel endpoint, so no worker
    holding its lease races the deletion. A draft, paused, or terminal run
    has nothing that could race and is always deletable. Deletion cascades
    through the run's hypotheses, evidence, reviews,
    citations, matches, safety decisions, reports, messages, checkpoints,
    metrics, and every other run-scoped table (enforced foreign keys, see
    ``app.store.runs_delete``); it cannot be undone.

    Returns:
        The deleted run's id and the row counts removed, per table --
        proof the cascade reached everything, not just the run row.

    Raises:
        HTTPException: 404 if the run does not exist (or is not owned by
            the caller); 403 for the shared demo run; 409 if the run is
            still active.
    """
    run = _run_or_404(run_id)
    _guard_deletable(run)
    counts = store.delete_run(run_id)
    return {"id": run_id, "deleted": True, "counts": counts}
