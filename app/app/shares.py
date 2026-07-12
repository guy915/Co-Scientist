"""Access-controlled public Goal Report sharing endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from app import store

router = APIRouter(tags=["shares"])


def _client_id(request: Request) -> str:
    """Read the browser ownership identifier used by the run API."""
    return request.headers.get("X-Client-ID", "")


def _owned_run(run_id: str, request: Request) -> store.RunRow:
    """Return a run only when the requesting browser owns it."""
    run = store.get_run(run_id)
    if run is None or run.client_id != _client_id(request):
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.post("/api/runs/{run_id}/shares")
async def create_share(run_id: str, request: Request) -> dict[str, Any]:
    """Enable public access by creating a unique revocable capability."""
    _owned_run(run_id, request)
    if store.get_latest_report(run_id) is None:
        raise HTTPException(status_code=409, detail="Goal Report not ready")
    return store.create_report_share(run_id, _client_id(request))


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
    if not store.revoke_report_share(
        share_id, run_id, _client_id(request)
    ):
        raise HTTPException(status_code=404, detail="share not found")
    return Response(status_code=204)


@router.get("/api/shared/{token}")
async def get_shared_report(token: str) -> dict[str, Any]:
    """Return a read-only Goal Report for one active capability token."""
    share = store.resolve_report_share(token)
    if share is None:
        raise HTTPException(status_code=404, detail="share not found")
    run = store.get_run(str(share["run_id"]))
    report = store.get_latest_report(str(share["run_id"]))
    if run is None or report is None:
        raise HTTPException(status_code=404, detail="Goal Report not found")
    return {
        "share_id": share["id"],
        "run": run.to_dict(),
        "report": report,
        "hypotheses": store.list_hypotheses(run.id),
        "evidence": store.list_evidence(run.id),
    }
