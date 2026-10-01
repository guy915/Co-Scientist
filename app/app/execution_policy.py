"""Server-derived execution policy for persisted research objects."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

from co_scientist.llm import scoped_campaign_mode
from fastapi import Request

from app.auth import principal_for_request
from app.config import settings

STANDARD = "standard"
CAMPAIGN = "campaign"
CAMPAIGN_MODEL_CONFIG_KEY = "campaign_model_name"
CAMPAIGN_MODEL_NAME = "openrouter/stealth/space-bunny-alpha"
_campaign_model: ContextVar[str | None] = ContextVar(
    "campaign_model", default=None
)


def campaign_model_for_config(config: Any = None) -> str | None:
    """Return a campaign route only when that run persisted one."""
    value = (
        config.get(CAMPAIGN_MODEL_CONFIG_KEY)
        if isinstance(config, dict)
        else None
    )
    return value if isinstance(value, str) and value.strip() else None


def effective_execution_model(configured_model: str | None) -> str | None:
    """Use the scoped campaign route before shaping an app model request."""
    return _campaign_model.get() or configured_model


@contextlib.contextmanager
def scoped_execution_policy(
    execution_policy: str, *, campaign_model_name: str | None = None
) -> Iterator[None]:
    """Apply one persisted policy to app and engine model calls."""
    with scoped_campaign_mode(execution_policy == CAMPAIGN):
        selected = _campaign_model.get()
        if selected is None and execution_policy == CAMPAIGN:
            selected = campaign_model_name
        token = _campaign_model.set(selected)
        try:
            yield
        finally:
            _campaign_model.reset(token)


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
