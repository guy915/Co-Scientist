from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request

from app import store
from app.auth import require_client_scope

router = APIRouter(tags=["account"])


def _run_export(run: store.RunRow) -> dict[str, Any]:
    return {
        "id": run.id,
        "title": run.title,
        "research_goal": run.research_goal,
        "status": run.status,
        "run_mode": run.profile,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "completed_at": run.completed_at,
        "report_markdown": store.read_report_markdown(run.id),
    }


def _staged_document_export(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": document["id"],
        "title": document["title"],
        "mime_type": document["mime_type"],
        "byte_size": document["byte_size"],
        "sha256": document["sha256"],
        "text": document["text"],
        "created_at": document["created_at"],
    }


@router.get("/api/account/export")
async def export_account_data(request: Request) -> dict[str, Any]:
    """Export every record owned by the caller's client identity (N11).

    A genuine, self-contained export rather than an index back to other
    endpoints: each run entry embeds its finalized report Markdown (the
    same text ``GET /api/runs/{id}/report.md`` serves) and each staged
    document embeds its extracted text. There is no operator/admin
    variant -- the export is always scoped to the requester's own id, the
    same identity every other endpoint in this app already trusts.

    An identity-less caller is refused outright rather than handed the
    pool of records under the empty subject. A silently empty export
    would be worse than the refusal: it reads as "you have no data"
    rather than "you did not say who you are".

    Raises:
        HTTPException: 400 when the caller declared no client identity.
    """
    owner = require_client_scope(request)
    runs = [_run_export(run) for run in store.list_runs(owner, limit=10_000)]
    documents = [
        _staged_document_export(document)
        for document in store.list_staged_documents_for_client(owner)
    ]
    return {
        "client_id": owner,
        "exported_at": time.time(),
        "runs": runs,
        "documents": documents,
        "interviews": store.list_interviews(owner),
    }
