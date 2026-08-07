"""Read-only run collection and report endpoints.

Split out of ``app.runs`` (which re-exports every name here and mounts
``router`` on its own, so the served route set is unchanged): the
per-run collection getters (hypotheses, evidence, matches, proximity,
reviews, safety, citations, metrics, logs, claim-evidence), the safety
adjudication endpoint that operates on those decisions, and the report
payload/Markdown reads.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app import store
from app.auth import client_id
from app.logs_api import RunLogQuery, logs_payload
from app.runs_models import SafetyAdjudicationRequest
from app.runs_support import _require_run, _run_or_404
from app.store import RunStatus

router = APIRouter()


@router.get("/{run_id}/hypotheses")
async def get_hypotheses(run_id: str) -> dict[str, Any]:
    """Return the run's hypotheses with Elo state, lineage, and verification."""
    run = _run_or_404(run_id)
    from app.report_render import _unverified_hypothesis_ids

    hyps = store.list_hypotheses(run_id)
    # Flag ideas without an evidence-supported claim so the UI can badge them
    # "Unverified" (they are ranked and published under the rank-and-publish
    # policy; only contradicted/unsafe ideas are withheld from the report).
    # Offline-backed runs (curated demos, deterministic offline engine runs)
    # are illustrative fixtures, not assessed science, so they are never badged
    # (they carry simulated "insufficient" claim rows that would otherwise
    # flag every idea). Keyed on the run's persisted backend, not the process
    # offline_mode(), so a real engine run created while offline is badged.
    if store.run_used_offline(run):
        for hyp in hyps:
            hyp["unverified"] = False
    else:
        unverified = _unverified_hypothesis_ids(run_id, None, hyps)
        for hyp in hyps:
            hyp["unverified"] = str(hyp.get("id")) in unverified
    return {"hypotheses": hyps}


@router.get("/{run_id}/evidence")
async def get_evidence(run_id: str) -> dict[str, Any]:
    """Return the literature evidence retrieved for the run."""
    _require_run(run_id)
    return {"evidence": store.list_evidence(run_id)}


@router.get("/{run_id}/matches")
async def get_matches(run_id: str) -> dict[str, Any]:
    """Return the run's tournament matches with Elo snapshots."""
    _require_run(run_id)
    return {"matches": store.list_matches(run_id)}


@router.get("/{run_id}/proximity")
async def get_proximity(run_id: str) -> dict[str, Any]:
    """Return the persisted weighted idea-proximity landscape."""
    _require_run(run_id)
    return {"proximity": store.list_proximity_edges(run_id)}


@router.get("/{run_id}/reviews")
async def get_reviews(run_id: str) -> dict[str, Any]:
    """Return reviewer and meta-review notes for the run."""
    _require_run(run_id)
    return {"reviews": store.list_reviews(run_id)}


@router.get("/{run_id}/safety")
async def get_safety(run_id: str) -> dict[str, Any]:
    """Return the run's intake/final safety-gate decisions."""
    _require_run(run_id)
    return {"safety": store.list_safety_decisions(run_id)}


async def _apply_adjudication_lifecycle(
    run: store.RunRow, decision: dict[str, Any], resolution: str
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
    """
    if decision["stage"] == "hypothesis":
        return
    if resolution == "rejected":
        store.update_run_status(
            run.id,
            RunStatus.BLOCKED,
            error="Safety reviewer rejected held content.",
        )
    elif run.status == RunStatus.PAUSED.value:
        await _release_approved_hold(run.id)


async def _release_approved_hold(run_id: str) -> None:
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
    from app.runs_lifecycle import _launch_resume

    await _launch_resume(run_id)


@router.post("/{run_id}/safety/{decision_id}/adjudicate")
async def adjudicate_safety(
    run_id: str,
    decision_id: int,
    body: SafetyAdjudicationRequest,
    request: Request,
) -> dict[str, Any]:
    """Resolve one held safety decision and update the run lifecycle."""
    run = _run_or_404(run_id)
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
    await _apply_adjudication_lifecycle(run, decision, body.resolution)
    return {"resolution": body.resolution, "decision_id": decision_id}


@router.get("/{run_id}/citations")
async def get_citations(run_id: str) -> dict[str, Any]:
    """Return the run's citation rows with classification states."""
    _require_run(run_id)
    return {"citations": store.list_citations(run_id)}


@router.get("/{run_id}/metrics")
async def get_metrics(run_id: str) -> dict[str, Any]:
    """Return the run's persisted execution metrics.

    The metrics dict (LLM calls, phase timings, artifact counts) is
    written on every durable node-commit boundary (finding L14), inside
    the same transaction that commits the node's checkpoint -- not on a
    timer -- so a still-running run already shows live, if partial,
    numbers here; the finalize drain then overwrites it with the final
    total. ``metrics`` is null only for a run that has not yet committed
    its first node (e.g. still bootstrapping).
    """
    _require_run(run_id)
    return {"metrics": store.get_run_metrics(run_id)}


@router.get("/{run_id}/logs")
async def get_run_logs(
    run_id: str,
    query: Annotated[RunLogQuery, Query()],
) -> dict[str, Any]:
    """Return the run's persisted application log records, oldest-first.

    Run-scoped view of ``GET /api/logs``: same filters and payload shape,
    with ``run_id`` fixed to this run.
    """
    _require_run(run_id)
    return logs_payload(query.for_run(run_id))


@router.get("/{run_id}/claim-evidence")
async def get_claim_evidence(run_id: str) -> dict[str, Any]:
    """Return the run's claim-level entailment graph (Milestone 5).

    Each edge is one atomic claim of a hypothesis with its assessed label
    (supports/contradicts/insufficient) and the exact supporting/contradicting
    passages that drove the verdict.
    """
    _require_run(run_id)
    return {"claim_evidence": store.list_claim_evidence(run_id)}


@router.get("/{run_id}/knowledge-facts")
async def get_knowledge_facts(
    run_id: str,
    kind: str | None = None,
    entity: str | None = None,
) -> dict[str, Any]:
    """Return the run's durable structured facts and contradictions (G14).

    One row per settled claim-evidence edge (``supports`` -> a fact,
    ``contradicts`` -> a contradiction), tagged with the entities its claim
    text mentions. Populated once the run's report is finalized; empty
    before then. Optional ``kind`` (``fact``/``contradiction``) and
    ``entity`` query params filter the result.
    """
    _require_run(run_id)
    return {
        "knowledge_facts": store.list_knowledge_facts(
            run_id, kind=kind, entity=entity
        )
    }


@router.get("/{run_id}/supervisor-plan")
async def get_supervisor_plan(run_id: str) -> dict[str, Any]:
    """Return the Supervisor's durable plan and allocation ledger (E19).

    ``plan`` carries the six planning blocks from the Supervisor's initial
    research plan; ``orchestrator_state``, ``decision_provenance``, and
    ``termination_reason`` describe how the run's scheduling ended.
    ``allocations`` is the append-only ledger of every task the adaptive
    orchestrator scheduled, in the order it scheduled them, each with the
    observable statistics behind that decision. Both are populated once the
    run finalizes; null/empty before then.
    """
    _require_run(run_id)
    plan = store.get_supervisor_plan(run_id)
    return {
        "plan": plan,
        "allocations": store.list_supervisor_allocations(run_id),
    }


@router.get("/{run_id}/report")
async def get_report(run_id: str) -> dict[str, Any]:
    """Return the latest structured report, or 404 before synthesis."""
    _require_run(run_id)
    report = store.get_latest_report(run_id)
    if not report:
        raise HTTPException(status_code=404, detail="no report yet")
    return report


@router.get("/{run_id}/report.md", response_class=PlainTextResponse)
async def get_report_markdown(run_id: str) -> PlainTextResponse:
    """Return the rendered Markdown report as a file download."""
    _require_run(run_id)
    md = store.read_report_markdown(run_id)
    if md is None:
        raise HTTPException(status_code=404, detail="no report yet")
    # Content-Disposition makes browsers save it as <run_id>.md.
    return PlainTextResponse(
        md,
        headers={
            "Content-Disposition": f'attachment; filename="{run_id}.md"',
        },
    )
