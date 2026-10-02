"""Attaching staged documents to a chat, and reporting what is attached.

Split out of ``app.interviews`` (which re-exports both names, so they stay
reachable as ``interviews._attach_documents`` /
``interviews._with_documents``). The interview reads its attachments on
every turn -- see ``interviews.prompts._attached_documents`` -- so a
document attached in the composer scopes the goal it was attached to,
rather than reaching the work only once a run exists.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app import staged_documents, store
from app.auth import client_id


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
