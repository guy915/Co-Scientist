"""Interview ownership, request credentials and staged document attachments."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from app import credentials, staged_documents, store
from app.auth import client_id
from app.execution_policy import CAMPAIGN, STANDARD


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


def _with_documents(interview: dict[str, Any]) -> dict[str, Any]:
    """Add the interview's attached-document summaries to its payload.

    Metadata only: the extracted text is the model's context, not something
    the transcript has to carry back to the browser on every turn.

    Args:
        interview: The interview row to annotate, modified in place.

    Returns:
        The same row, carrying a ``documents`` list.
    """
    attached = store.list_interview_documents(str(interview["id"]))
    interview["documents"] = [
        staged_documents.document_summary(d) for d in attached
    ]
    return interview


def _attach_documents(
    interview_id: str, document_ids: list[str], request: Request
) -> None:
    """Attach staged documents to an interview, refusing an unowned id.

    Args:
        interview_id: The chat the documents belong to.
        document_ids: Ids staged through ``/api/documents``.
        request: Incoming request, used to read the owning identity.

    Raises:
        HTTPException: 404 when an id is unknown or belongs to another
            client (see ``staged_documents.resolve_owned_documents``).
    """
    if not document_ids:
        return
    owner = client_id(request)
    staged_documents.resolve_owned_documents(document_ids, owner)
    store.attach_documents_to_interview(interview_id, document_ids, owner)
