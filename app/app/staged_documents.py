"""Shared staged-document ownership checks and client metadata views.

Run creation and interview attachment handling resolve the entire requested
set before writing anything. These helpers live below their HTTP routers so
neither domain has to import the document endpoint module.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app import store


def resolve_owned_documents(
    document_ids: list[str], owner: str
) -> list[dict[str, Any]]:
    """Resolve staged documents the caller owns, or refuse the whole set.

    All-or-nothing on purpose: a request that names a document is asking for
    work grounded in it, so silently proceeding with the subset that
    resolved would produce an answer the scientist has no way to know was
    ungrounded. Refusing before anything is written is also what keeps run
    creation from leaving a half-attached run behind.

    Args:
        document_ids: The ids the request named.
        owner: The calling client identity.

    Returns:
        The resolved rows, in the order they were named.

    Raises:
        HTTPException: 404 when any id is unknown or owned by someone else.
    """
    if not document_ids:
        return []
    documents = store.get_staged_documents(document_ids, owner)
    if len(documents) != len(document_ids):
        raise HTTPException(
            status_code=404, detail="attached document not found"
        )
    return documents


def document_summary(document: dict[str, Any]) -> dict[str, Any]:
    """Summarize one staged document for a client payload, without its text."""
    return {
        "id": document["id"],
        "title": document["title"],
        "mime_type": document["mime_type"],
        "byte_size": document["byte_size"],
    }
