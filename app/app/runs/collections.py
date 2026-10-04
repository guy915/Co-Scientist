from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

import app.api_contracts as contracts
from app import store
from app.api_contracts.reports import Report
from app.auth import require_bearer_principal
from app.logs_api import RunLogQuery, logs_payload
from app.report import unverified_hypothesis_ids
from app.runs.lifecycle import adjudicate_safety
from app.runs.support import _require_run, _run_or_404

router = APIRouter()


@router.get("/{run_id}/hypotheses", response_model=contracts.HypothesesResponse)
async def get_hypotheses(run_id: str) -> dict[str, Any]:
    """Return the run's hypotheses with Elo state, lineage, and verification."""
    run = _run_or_404(run_id)
    hyps = store.list_hypotheses(run_id)
    # Offline badges describe persisted run provenance, never the current
    # process
    # backend.
    if store.run_used_offline(run):
        for hyp in hyps:
            hyp["unverified"] = False
    else:
        unverified = unverified_hypothesis_ids(run_id, None, hyps)
        for hyp in hyps:
            hyp["unverified"] = str(hyp.get("id")) in unverified
    return {"hypotheses": hyps}


@router.get("/{run_id}/evidence", response_model=contracts.EvidenceResponse)
async def get_evidence(run_id: str) -> dict[str, Any]:
    """Return the literature evidence retrieved for the run."""
    _require_run(run_id)
    return {"evidence": store.list_evidence(run_id)}


@router.get("/{run_id}/matches", response_model=contracts.MatchesResponse)
async def get_matches(run_id: str) -> dict[str, Any]:
    """Return the run's tournament matches with Elo snapshots."""
    _require_run(run_id)
    return {"matches": store.list_matches(run_id)}


@router.get("/{run_id}/proximity", response_model=contracts.ProximityResponse)
async def get_proximity(run_id: str) -> dict[str, Any]:
    """Return the persisted weighted idea-proximity landscape."""
    _require_run(run_id)
    return {"proximity": store.list_proximity_edges(run_id)}


@router.get("/{run_id}/reviews", response_model=contracts.ReviewsResponse)
async def get_reviews(run_id: str) -> dict[str, Any]:
    """Return reviewer and meta-review notes for the run."""
    _require_run(run_id)
    return {"reviews": store.list_reviews(run_id)}


@router.get("/{run_id}/safety", response_model=contracts.SafetyResponse)
async def get_safety(run_id: str) -> dict[str, Any]:
    """Return the run's intake/final safety-gate decisions."""
    _require_run(run_id)
    return {"safety": store.list_safety_decisions(run_id)}


@router.get("/{run_id}/outcomes", response_model=contracts.OutcomesResponse)
async def get_hypothesis_outcomes(
    run_id: str, request: Request
) -> dict[str, Any]:
    """Return the run's researcher-recorded hypothesis outcomes."""
    run = _run_or_404(run_id)
    if run.client_id != store.DEMO_CLIENT_ID:
        researcher = require_bearer_principal(request)
        if run.client_id != researcher.subject:
            raise HTTPException(status_code=404, detail="run not found")
    return {"outcomes": store.list_hypothesis_outcomes(run_id)}


def _task_payload(task: Any) -> dict[str, Any]:
    return {
        "id": task.id,
        "task_type": task.task_type,
        "status": task.status,
        "attempt": task.attempt,
        "max_attempts": task.max_attempts,
        "error": task.error,
        "attempts": list(task.attempts),
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
    }


@router.get("/{run_id}/tasks")
async def get_tasks(run_id: str) -> dict[str, Any]:
    """Return the run's durable tasks, including retry-attempt history."""
    _require_run(run_id)
    return {"tasks": [_task_payload(t) for t in store.list_tasks(run_id)]}


# Literal routes precede dynamic IDs because the router uses first-match
# ordering.
router.post("/{run_id}/safety/{decision_id}/adjudicate")(adjudicate_safety)


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


@router.get("/{run_id}/claim-evidence", response_model=contracts.ClaimsResponse)
async def get_claim_evidence(run_id: str) -> dict[str, Any]:
    """Return the run's claim-level entailment graph (Milestone 5).

    Each edge is one atomic claim of a hypothesis with its assessed label
    (an ``EntailmentLabel`` value; ``app.claims.gate`` says what each
    means) and the exact supporting/contradicting passages that drove the
    verdict.
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


@router.get("/{run_id}/report", response_model=Report)
async def get_report(run_id: str) -> dict[str, Any]:
    """Return the latest structured report, or 404 before synthesis."""
    _require_run(run_id)
    report = store.get_latest_report(run_id)
    if not report:
        raise HTTPException(status_code=404, detail="no report yet")
    return report


@router.get("/{run_id}/report.md", response_class=PlainTextResponse)
async def get_report_markdown(run_id: str) -> PlainTextResponse:
    """Return the rendered Goal Report document as a file download."""
    _require_run(run_id)
    md = store.read_report_markdown(run_id)
    if md is None:
        raise HTTPException(status_code=404, detail="no report yet")
    return PlainTextResponse(
        md,
        headers={
            "Content-Disposition": f'attachment; filename="{run_id}.md"',
        },
    )
