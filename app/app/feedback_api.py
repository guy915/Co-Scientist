from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from app.auth import require_client_scope
from app.config import settings
from app.store import feedback

router = APIRouter(tags=["feedback"])


class FeedbackRequest(BaseModel):
    category: feedback.Category
    message: str = Field(min_length=1, max_length=8_000)
    diagnostics: str = Field(max_length=100_000)
    url: str = Field(max_length=2_048)
    # Reported context only; this field never authorizes artifact reads.
    run_id: str | None = Field(None, max_length=128)

    @field_validator("message")
    @classmethod
    def nonempty_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("a message is required")
        return value


@router.post("/api/feedback", status_code=201)
async def submit_feedback(body: FeedbackRequest, request: Request) -> dict[str, str]:
    owner = require_client_scope(request)
    host = request.client.host if request.client else "unknown"
    host_key = hashlib.sha256(host.encode()).hexdigest()
    try:
        identity = feedback.submit(owner, host_key, feedback.Submission(**body.model_dump()))
    except feedback.RateExceededError as exc:
        raise HTTPException(
            status_code=429, detail=str(exc), headers={"Retry-After": "60"}
        ) from exc
    return {"id": identity, "status": "submitted"}


@router.get("/api/feedback/admin")
async def read_feedback(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, list[feedback.FeedbackRow]]:
    # Unlike local diagnostics, this endpoint always requires the configured
    # maintainer token. Host/forwarding headers cannot grant access.
    supplied = request.headers.get("X-Logs-Token", "")
    token = settings.logs_admin_token
    if not token or not supplied or not hmac.compare_digest(supplied, token):
        raise HTTPException(status_code=403, detail="maintainer access required")
    return {"feedback": feedback.list_feedback(limit=limit, offset=offset)}
