"""Pilot feedback submission, plus account-level export and self-service.

Feedback used to be written straight to the store with no read path at
all, reviewed only out of band (N12). It now also carries a per-caller
read/delete pair, and this module is where the account-level data export
(N11) lives too -- both are owner-scoped the same way every other
``client_id``-keyed endpoint in this app is, so both ride on this
router's plain (unprefixed) path style rather than adding a new top-level
router.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import store
from app.audience import AUDIENCE_PATTERN
from app.auth import client_id, require_client_scope

logger = logging.getLogger(__name__)

router = APIRouter(tags=["feedback"])

# Categories the form offers. Kept in lockstep with FEEDBACK_CATEGORIES in
# the frontend's audience_content.ts, which renders the same set.
FEEDBACK_CATEGORIES: tuple[str, ...] = (
    "bug",
    "suggestion",
    "question",
    "praise",
)

CATEGORY_PATTERN: str = f"^({'|'.join(FEEDBACK_CATEGORIES)})$"

# Long enough for a considered note, short enough that a runaway paste
# cannot fill the database.
MAX_MESSAGE_LENGTH: int = 4000


class FeedbackRequest(BaseModel):
    """One submitted feedback note."""

    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    category: str = Field(pattern=CATEGORY_PATTERN)
    audience: str | None = Field(None, pattern=AUDIENCE_PATTERN)


@router.post("/api/feedback", status_code=201)
async def submit_feedback(
    req: FeedbackRequest, request: Request
) -> dict[str, Any]:
    """Store one feedback note from the workspace.

    Args:
        req: The submitted note.
        request: Incoming request, used to attribute the note to a browser.

    Returns:
        The stored note.
    """
    note = store.append_feedback(
        client_id=client_id(request),
        audience=req.audience or "general",
        category=req.category,
        message=req.message.strip(),
    )
    # The note body stays in the database only; the log records that one
    # arrived so submissions are traceable without copying their contents
    # into the deployment's log stream.
    logger.info(
        "Feedback received (id=%s, %s, %s)",
        note["id"],
        note["audience"],
        note["category"],
    )
    return note


@router.get("/api/feedback")
async def list_own_feedback(request: Request) -> dict[str, Any]:
    """List the caller's own feedback notes, newest first (N12).

    Scoped to the submitting client id, like every other read in this
    app -- there is no operator view here (that remains the out-of-band
    review the module used to require for every note).

    An identity-less caller lists nothing rather than the pool of notes
    every other identity-less caller also submitted: the empty subject is
    not a scope, it is the absence of one (see ``require_client_scope``).
    """
    owner = client_id(request)
    if not owner:
        return {"feedback": []}
    return {"feedback": store.list_feedback_for_client(owner)}


@router.delete("/api/feedback/{feedback_id}", status_code=204)
async def delete_own_feedback(feedback_id: int, request: Request) -> Response:
    """Delete one feedback note the caller submitted (N12).

    Raises:
        HTTPException: 404 if the note is unknown or was submitted by
            another client.
    """
    # An empty subject must not match the notes pooled under it.
    owner = client_id(request)
    deleted = bool(owner) and store.delete_feedback(feedback_id, owner)
    if not deleted:
        raise HTTPException(status_code=404, detail="feedback note not found")
    return Response(status_code=204)


def _run_export(run: store.RunRow) -> dict[str, Any]:
    """One run's exportable record, including its finalized report text."""
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
    """One staged document's exportable record, including its full text."""
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
        "feedback": store.list_feedback_for_client(owner),
        "interviews": store.list_interviews(owner),
    }
