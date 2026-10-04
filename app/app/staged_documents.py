from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app import store


def resolve_owned_documents(
    document_ids: list[str], owner: str
) -> list[dict[str, Any]]:
    """Refuse the entire set before writes: silently dropping a named
    attachment would produce ungrounded work and half-attached runs.
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
    return {
        "id": document["id"],
        "title": document["title"],
        "mime_type": document["mime_type"],
        "byte_size": document["byte_size"],
    }
