from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class Principal:
    subject: str


def principal_for_request(request: Request) -> Principal:
    return Principal(request.headers.get("X-Client-ID", ""))


def client_id(request: Request) -> str:
    return principal_for_request(request).subject


def require_client_scope(request: Request) -> str:
    """An empty identity would pool private records with every other
    unidentified caller; refuse creation rather than assigning that
    scope.
    """
    subject = client_id(request)
    if not subject:
        raise HTTPException(
            status_code=400,
            detail="an X-Client-ID header is required to create this",
        )
    return subject
