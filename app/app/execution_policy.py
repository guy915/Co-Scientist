"""Server-derived execution policy for persisted research objects."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.auth import principal_for_request
from app.config import settings

STANDARD = "standard"
CAMPAIGN = "campaign"


def resolve_execution_policy(
    request: Request, interview: dict[str, Any] | None = None
) -> str:
    """Resolve a monotone policy from trusted server state only."""
    if interview and interview.get("execution_policy") == CAMPAIGN:
        return CAMPAIGN
    principal = principal_for_request(request)
    if (
        principal is not None
        and principal.method == "bearer"
        and principal.subject in settings.campaign_researcher_ids
    ):
        return CAMPAIGN
    return STANDARD
