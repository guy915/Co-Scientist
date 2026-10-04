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

# Process-local IP limits assume one API replica; replicated deployments need a
# shared limiter.
_exchange_hits: dict[str, list[float]] = {}
_MAX_SCOPES = 4096
_WINDOW_SECONDS = 60


def check_exchange_rate(request: Request) -> None:
    now = time.monotonic()
    host = request.client.host if request.client else "unknown"
    for stale in [
        key
        for key, hits in _exchange_hits.items()
        if not hits or now - hits[-1] >= _WINDOW_SECONDS
    ]:
        del _exchange_hits[stale]
    hits = [
        timestamp
        for timestamp in _exchange_hits.get(host, [])
        if now - timestamp < _WINDOW_SECONDS
    ]
    full = host not in _exchange_hits and len(_exchange_hits) >= _MAX_SCOPES
    if full or len(hits) >= settings.auth_exchange_per_minute:
        raise HTTPException(
            status_code=429,
            detail="access code exchange rate exceeded",
            headers={"Retry-After": str(_WINDOW_SECONDS)},
        )
    hits.append(now)
    _exchange_hits[host] = hits


router = APIRouter(prefix="/api/auth", tags=["auth"])


@dataclass(frozen=True)
class Principal:
    subject: str
    method: str


class AccessCodeRequest(BaseModel):
    """One configured researcher invite/access code."""

    access_code: str = Field(..., min_length=1, max_length=512)


def auth_required() -> bool:
    return settings.auth_mode.strip().lower() == "required"


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _secret() -> bytes:
    if not settings.auth_secret:
        raise RuntimeError(
            "AUTH_SECRET is required when authentication is used"
        )
    return settings.auth_secret.encode()


def create_session_token(subject: str, now: int | None = None) -> str:
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
    """Credentials travel in headers only: query strings leak through
    browser history, proxy logs and referrers.
    """
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        return verify_session_token(authorization.removeprefix("Bearer "))
    if auth_required():
        return None
    client_id = request.headers.get("X-Client-ID", "")
    return Principal(client_id, "compatibility")


def require_principal(request: Request) -> Principal:
    principal = principal_for_request(request)
    if principal is None:
        raise HTTPException(
            status_code=401, detail="researcher access required"
        )
    return principal


def require_bearer_principal(request: Request) -> Principal:
    principal = require_principal(request)
    if principal.method != "bearer":
        raise HTTPException(
            status_code=401, detail="verified researcher session required"
        )
    return principal


def client_id(request: Request) -> str:
    return require_principal(request).subject


def require_client_scope(request: Request) -> str:
    """An empty identity would pool private records with every other
    unidentified caller; refuse creation rather than assigning that
    scope.
    """
    subject = client_id(request)
    if not subject:
        raise HTTPException(
            status_code=400,
            detail=(
                "an X-Client-ID header (or a researcher session) is "
                "required to create this"
            ),
        )
    return subject


def _configured_codes() -> dict[str, str]:
    """Malformed invite configuration fails closed rather than granting
    accidental access.
    """
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
async def exchange_access_code(
    body: AccessCodeRequest, request: Request
) -> dict[str, object]:
    """Exchange one invite code for a signed researcher session."""
    check_exchange_rate(request)
    match = next(
        (
            subject
            for subject, code in _configured_codes().items()
            if hmac.compare_digest(body.access_code.encode(), code.encode())
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
