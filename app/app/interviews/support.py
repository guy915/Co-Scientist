"""Ownership and request-credential guards shared by interview routes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from app import credentials, store
from app.auth import client_id
from app.execution_policy import CAMPAIGN, STANDARD
from app.interviews.documents import _with_documents


def owned_interview(interview_id: str, request: Request) -> dict[str, Any]:
    """Return an owned interview or raise without leaking its existence.

    An empty subject (no ``X-Client-ID`` header) never matches, even an
    interview whose own ``client_id`` happens to be empty too -- the same
    "an identity-less caller owns nothing" rule ``create_interview``
    enforces at creation time and ``app.main._run_ownership_response``
    enforces for runs.
    """
    interview = store.get_interview(interview_id)
    subject = client_id(request)
    if not subject or interview is None or interview["client_id"] != subject:
        raise HTTPException(status_code=404, detail="interview not found")
    return _with_documents(interview)


def request_byok(
    request: Request, execution_policy: str = STANDARD
) -> credentials.ByokCredential | None:
    """Parse optional BYOK headers for an interview turn, 400 if malformed.

    Interviews predate any run, so their model calls can only ride a
    per-request header credential (nothing is stored server-side).
    """
    try:
        credential = credentials.credential_from_headers(request.headers)
    except credentials.ByokRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if execution_policy == CAMPAIGN and credential is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "campaign interviews cannot use bring-your-own-key credentials"
            ),
        )
    return credential
