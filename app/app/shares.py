from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from app import store
from app.api_contracts import SharesResponse
from app.api_contracts.reports import SharedGoalReport
from app.api_contracts.runs import ReportShare
from app.auth import client_id
from app.evidence_chunking import parent_evidence_id
from app.report import exclude_unsafe_hypotheses, released_claim_evidence

router = APIRouter(tags=["shares"])

# Public evidence excludes private attachment bodies and upload provenance;
# retraction remains a reader-visible fact.
_PUBLIC_EVIDENCE_FIELDS = (
    "id",
    "title",
    "source",
    "url",
    "authors",
    "year",
    "available",
    "retracted",
)


def _owned_run(run_id: str, request: Request) -> store.RunRow:
    run = store.get_run(run_id)
    if run is None or run.client_id != client_id(request):
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.post("/api/runs/{run_id}/shares", response_model=ReportShare)
async def create_share(run_id: str, request: Request) -> dict[str, Any]:
    """Enable public access by creating a unique revocable capability."""
    _owned_run(run_id, request)
    if store.get_latest_report(run_id) is None:
        raise HTTPException(status_code=409, detail="Goal Report not ready")
    return store.create_report_share(run_id, client_id(request))


@router.get("/api/runs/{run_id}/shares", response_model=SharesResponse)
async def list_shares(run_id: str, request: Request) -> dict[str, Any]:
    """List active share grants for an owned run."""
    _owned_run(run_id, request)
    return {"shares": store.list_report_shares(run_id)}


@router.delete("/api/runs/{run_id}/shares/{share_id}", status_code=204)
async def revoke_share(
    run_id: str,
    share_id: str,
    request: Request,
) -> Response:
    """Revoke one public capability immediately."""
    _owned_run(run_id, request)
    if not store.revoke_report_share(share_id, run_id, client_id(request)):
        raise HTTPException(status_code=404, detail="share not found")
    return Response(status_code=204)


def _public_run_view(run: store.RunRow) -> dict[str, Any]:
    """Public capability access must not expose raw configuration, ownership
    or internal error state.
    """
    return {
        "title": run.title,
        "research_goal": run.research_goal,
        "run_mode": run.profile,
    }


def _referenced_evidence_ids(edges: list[dict[str, Any]]) -> set[str]:
    """Chunk provenance resolves to parent article IDs before matching
    stored evidence rows.
    """
    ids: set[str] = set()
    for edge in edges:
        for key in ("supporting", "contradicting"):
            for span in edge.get(key) or []:
                raw = (
                    span.get("evidence_id") if isinstance(span, dict) else None
                )
                if raw:
                    ids.add(parent_evidence_id(str(raw)))
    return ids


def _released_content(
    run_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Shares apply the same publication gates as reports and expose only
    released ideas and their referenced sources.
    """
    all_hypotheses = store.list_hypotheses(run_id)
    claim_edges = store.list_claim_evidence(run_id)
    hypotheses = exclude_unsafe_hypotheses(
        run_id, all_hypotheses, None, claim_edges
    )
    evidence = store.list_evidence(run_id)
    released_edges = released_claim_evidence(hypotheses, claim_edges, evidence)
    referenced = _referenced_evidence_ids(released_edges)
    released_evidence = [
        {field: item.get(field) for field in _PUBLIC_EVIDENCE_FIELDS}
        for item in evidence
        if str(item.get("id") or "") in referenced
    ]
    return hypotheses, released_evidence


@router.get("/api/shared/{token}", response_model=SharedGoalReport)
async def get_shared_report(token: str) -> dict[str, Any]:
    """Return a read-only Goal Report for one active capability token."""
    share = store.resolve_report_share(token)
    if share is None:
        raise HTTPException(status_code=404, detail="share not found")
    shared_run_id = str(share["run_id"])
    run = store.get_run(shared_run_id)
    report = store.get_latest_report(shared_run_id)
    if run is None or report is None:
        raise HTTPException(status_code=404, detail="Goal Report not found")
    hypotheses, evidence = _released_content(run.id)
    return {
        "share_id": share["id"],
        "run": _public_run_view(run),
        "report": report,
        "hypotheses": hypotheses,
        "evidence": evidence,
    }
