"""Safety adjudication: a reviewer's verdict on a held decision.

Split out of ``runs_collections`` because, unlike that module's reads,
adjudication changes the run's lifecycle: approving an intake or final hold
relaunches the run through ``runs_lifecycle._launch_resume``, and rejecting
one blocks it. Both consequences are guarded by the lifecycle revision read
at admission, so a cancel, pause or resume that lands in between wins.

The handler is a plain function: ``runs_collections`` registers it, in the
slot the served route table has always listed it at.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from app import store
from app.auth import client_id
from app.runs_lifecycle import _launch_resume
from app.runs_models import SafetyAdjudicationRequest
from app.runs_resume_admission import (
    lifecycle_revision,
    resume_admission_snapshot,
)
from app.store import RunStatus


async def _apply_adjudication_lifecycle(
    run: store.RunRow,
    decision: dict[str, Any],
    resolution: str,
    *,
    expected_lifecycle_revision: int,
) -> None:
    """Apply the run-lifecycle consequence of one adjudicated decision.

    Intake/final holds gate the run's whole goal or report, so a rejection
    blocks the run and an approval releases it. A hypothesis-stage hold
    concerns one idea the engine already kept out of the pool and the
    report; rejecting it confirms the exclusion, and the recorded
    resolution is the verdict -- the run's lifecycle is untouched.

    Args:
        run: The run whose decision was adjudicated.
        decision: The resolved decision row (carries its ``stage``).
        resolution: ``"approved"`` or ``"rejected"``.
        expected_lifecycle_revision: Transition revision observed at admission.
    """
    if decision["stage"] == "hypothesis":
        return
    if resolution == "rejected":
        _block_rejected_run_if_current(
            run, expected_lifecycle_revision=expected_lifecycle_revision
        )
    elif run.status == RunStatus.PAUSED.value:
        await _release_approved_hold(
            run.id,
            expected_status=run.status,
            expected_lifecycle_revision=expected_lifecycle_revision,
        )


def _block_rejected_run_if_current(
    run: store.RunRow, *, expected_lifecycle_revision: int
) -> None:
    """Block a rejected run only while its admission state is unchanged."""
    with store.transaction() as conn:
        current = store.get_run(run.id, conn=conn)
        if current is None:
            raise HTTPException(status_code=404, detail="run not found")
        if (
            current.status != run.status
            or lifecycle_revision(run.id, conn=conn)
            != expected_lifecycle_revision
        ):
            raise HTTPException(
                status_code=409, detail="run status changed during adjudication"
            )
        store.update_run_status(
            run.id,
            RunStatus.BLOCKED,
            error="Safety reviewer rejected held content.",
            conn=conn,
        )


async def _release_approved_hold(
    run_id: str,
    *,
    expected_status: str,
    expected_lifecycle_revision: int,
) -> None:
    """Relaunch a run whose intake or final hold a reviewer just approved.

    The gate that held the run parked its task rather than completing it
    (``engine_tasks.SafetyHoldError``), so the boundary the run stopped at
    is still on the queue waiting to be released -- which is exactly what
    the resume path does. Approval used to only rewrite the run's status,
    which left the queue untouched: the holding task had already succeeded,
    re-enqueueing its boundary hit the same idempotency key and created
    nothing, and the run sat with no claimable work forever.

    The stage is not re-screened on the way back through: the escalation
    wrapper skips a stage a reviewer approved (``screen_with_escalation``),
    so a fresh contextual verdict cannot re-hold what a person released.
    """
    await _launch_resume(
        run_id,
        expected_status=expected_status,
        expected_lifecycle_revision=expected_lifecycle_revision,
    )


async def adjudicate_safety(
    run_id: str,
    decision_id: int,
    body: SafetyAdjudicationRequest,
    request: Request,
) -> dict[str, Any]:
    """Resolve one held safety decision and update the run lifecycle."""
    run, revision = resume_admission_snapshot(run_id)
    reviewer = client_id(request)
    if not reviewer:
        raise HTTPException(
            status_code=403, detail="an identified reviewer is required"
        )
    resolved = store.resolve_safety_decision(
        run_id, decision_id, body.resolution, reviewer
    )
    if not resolved:
        raise HTTPException(
            status_code=409,
            detail="decision is not reviewable or was already resolved",
        )
    decisions = store.list_safety_decisions(run_id)
    decision = next(item for item in decisions if item["id"] == decision_id)
    await _apply_adjudication_lifecycle(
        run,
        decision,
        body.resolution,
        expected_lifecycle_revision=revision,
    )
    return {"resolution": body.resolution, "decision_id": decision_id}
