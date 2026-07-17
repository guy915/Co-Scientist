"""Invite-based researcher authentication with signed bearer sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


@dataclass(frozen=True)
class Principal:
    """Verified researcher identity and its authentication method."""

    subject: str
    method: str


class AccessCodeRequest(BaseModel):
    """One configured researcher invite/access code."""

    access_code: str = Field(..., min_length=1, max_length=512)


def auth_required() -> bool:
    """Return whether private API routes require verified sessions."""
    return settings.auth_mode.strip().lower() == "required"


def _b64encode(value: bytes) -> str:
    """Encode token bytes without padding."""
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    """Decode an unpadded URL-safe token segment."""
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _secret() -> bytes:
    """Return configured signing secret or reject unsafe required mode."""
    if not settings.auth_secret:
        raise RuntimeError(
            "AUTH_SECRET is required when authentication is used"
        )
    return settings.auth_secret.encode()


def create_session_token(subject: str, now: int | None = None) -> str:
    """Create a signed, expiring researcher session token."""
    issued_at = int(time.time()) if now is None else now
    payload = {
        "sub": subject,
        "iat": issued_at,
        "exp": issued_at + settings.auth_session_hours * 3600,
        "v": 1,
    }
    encoded = _b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    )
    signature = _b64encode(
        hmac.new(_secret(), encoded.encode(), hashlib.sha256).digest()
    )
    return f"{encoded}.{signature}"


def verify_session_token(token: str, now: int | None = None) -> Principal:
    """Verify signature, shape, and expiry, returning the researcher."""
    try:
        encoded, signature = token.split(".", 1)
        expected = _b64encode(
            hmac.new(_secret(), encoded.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        payload = json.loads(_b64decode(encoded))
        current = int(time.time()) if now is None else now
        subject = payload.get("sub")
        if (
            not isinstance(subject, str)
            or not subject
            or payload.get("v") != 1
            or int(payload.get("exp", 0)) <= current
        ):
            raise ValueError("invalid or expired payload")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="invalid session") from exc
    return Principal(subject=subject, method="bearer")


def principal_for_request(request: Request) -> Principal | None:
    """Resolve a verified bearer principal or compatibility client scope."""
    authorization = request.headers.get("Authorization", "")
    query_params = getattr(request, "query_params", {})
    query_token = query_params.get("access_token", "")
    if authorization.startswith("Bearer "):
        return verify_session_token(authorization.removeprefix("Bearer "))
    if query_token:
        return verify_session_token(query_token)
    if auth_required():
        return None
    client_id = request.headers.get("X-Client-ID") or query_params.get(
        "client_id", ""
    )
    return Principal(client_id, "compatibility")


def require_principal(request: Request) -> Principal:
    """Return the current principal or raise an authentication challenge."""
    principal = principal_for_request(request)
    if principal is None:
        raise HTTPException(
            status_code=401, detail="researcher access required"
        )
    return principal


def client_id(request: Request) -> str:
    """Return the verified researcher subject or compatibility scope."""
    return require_principal(request).subject


def _configured_codes() -> dict[str, str]:
    """Parse configured researcher-to-code mapping, failing closed."""
    try:
        value = json.loads(settings.researcher_access_codes)
    except json.JSONDecodeError as exc:
        raise RuntimeError("RESEARCHER_ACCESS_CODES must be JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("RESEARCHER_ACCESS_CODES must be an object")
    return {
        str(subject): str(code)
        for subject, code in value.items()
        if subject and code
    }


@router.post("/exchange")
async def exchange_access_code(body: AccessCodeRequest) -> dict[str, object]:
    """Exchange one invite code for a signed researcher session."""
    match = next(
        (
            subject
            for subject, code in _configured_codes().items()
            if hmac.compare_digest(body.access_code, code)
        ),
        None,
    )
    if match is None:
        raise HTTPException(status_code=401, detail="invalid access code")
    return {
        "access_token": create_session_token(match),
        "token_type": "bearer",
        "expires_in": settings.auth_session_hours * 3600,
        "researcher_id": match,
    }
