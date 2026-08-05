"""Access-controlled public Goal Report sharing endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from app import store
from app.auth import client_id
from app.report_render import (
    _exclude_unsafe_hypotheses,
    _released_claim_evidence,
)

router = APIRouter(tags=["shares"])

# Evidence fields a public share may surface: a source's bibliographic
# identity, which the released report cites by title/url. The ``abstract``
# column stays out because attachment evidence stores the private document
# body there, and the report publishes no evidence full text; upload
# provenance (digests, sizes, extractor) is likewise owner-only.
_PUBLIC_EVIDENCE_FIELDS = (
    "id",
    "title",
    "source",
    "url",
    "authors",
    "year",
    "available",
)


def _owned_run(run_id: str, request: Request) -> store.RunRow:
    """Return a run only when the requesting browser owns it."""
    run = store.get_run(run_id)
    if run is None or run.client_id != client_id(request):
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.post("/api/runs/{run_id}/shares")
async def create_share(run_id: str, request: Request) -> dict[str, Any]:
    """Enable public access by creating a unique revocable capability."""
    _owned_run(run_id, request)
    if store.get_latest_report(run_id) is None:
        raise HTTPException(status_code=409, detail="Goal Report not ready")
    return store.create_report_share(run_id, client_id(request))


@router.get("/api/runs/{run_id}/shares")
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
    """The only run fields the public page renders.

    The full row carries the run's raw configuration, ownership, and error
    state, which a share capability must not hand out.
    """
    return {
        "title": run.title,
        "research_goal": run.research_goal,
        "run_mode": run.profile,
    }


def _referenced_evidence_ids(edges: list[dict[str, Any]]) -> set[str]:
    """Evidence ids cited by released claim edges' provenance spans."""
    ids: set[str] = set()
    for edge in edges:
        for key in ("supporting", "contradicting"):
            for span in edge.get(key) or []:
                raw = (
                    span.get("evidence_id") if isinstance(span, dict) else None
                )
                if raw:
                    ids.add(str(raw))
    return ids


def _released_content(
    run_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A run's hypotheses and evidence as the Goal Report releases them.

    Reuses the finalize path's publication gates -- the same
    ``_exclude_unsafe_hypotheses`` / ``_released_claim_evidence`` pair the
    report builder applies -- so a share exposes exactly the ranked ideas
    the report published and only the evidence those ideas cite. Safety-
    blocked, review-rejected, deduplicated, and contradicted ideas stay
    out, and evidence rows are reduced to their bibliographic identity.

    Args:
        run_id: Identifier of the shared run.

    Returns:
        A tuple of (released hypotheses, released evidence views).
    """
    all_hypotheses = store.list_hypotheses(run_id)
    claim_edges = store.list_claim_evidence(run_id)
    hypotheses = _exclude_unsafe_hypotheses(
        run_id, all_hypotheses, None, claim_edges
    )
    evidence = store.list_evidence(run_id)
    released_edges = _released_claim_evidence(hypotheses, claim_edges, evidence)
    referenced = _referenced_evidence_ids(released_edges)
    released_evidence = [
        {field: item.get(field) for field in _PUBLIC_EVIDENCE_FIELDS}
        for item in evidence
        if str(item.get("id") or "") in referenced
    ]
    return hypotheses, released_evidence


@router.get("/api/shared/{token}")
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
