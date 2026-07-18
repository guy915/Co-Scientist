"""Pilot feedback submission endpoint.

Feedback is written straight to the store; there is no read endpoint, since
notes are reviewed out of band rather than shown back in the workspace.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app import store
from app.audience import AUDIENCE_PATTERN
from app.auth import client_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["feedback"])

# Categories the form offers. Kept in lockstep with FEEDBACK_CATEGORIES in
# the frontend's audience_content.ts, which renders the same set.
FEEDBACK_CATEGORIES: tuple[str, ...] = ("bug", "idea", "confusing")

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
