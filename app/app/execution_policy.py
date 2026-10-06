from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

from co_scientist.llm import scoped_campaign_mode
from co_scientist.llm.profile import is_free_route
from fastapi import Request

from app.auth import principal_for_request
from app.config import settings

STANDARD = "standard"
CAMPAIGN = "campaign"
CAMPAIGN_MODEL_CONFIG_KEY = "campaign_model_name"
CAMPAIGN_MODEL_NAME = "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
_campaign_model: ContextVar[str | None] = ContextVar("campaign_model", default=None)


def campaign_model_for_config(config: Any = None) -> str | None:
    value = config.get(CAMPAIGN_MODEL_CONFIG_KEY) if isinstance(config, dict) else None
    return value if isinstance(value, str) and value.strip() else None


# Engine tasks of a run stamped with this key admit only zero-price requests,
# so a lost lease can replay without an unknown spend.
ZERO_COST_CONFIG_KEY = "zero_cost_admission"


def zero_cost_admission_for_config(config: Any = None) -> bool:
    return isinstance(config, dict) and config.get(ZERO_COST_CONFIG_KEY) is True


def deployment_routes_are_free() -> bool:
    models = (
        settings.model_name,
        settings.effective_supervisor_model,
        settings.claim_verifier_model,
        settings.semantic_safety_model,
    )
    return all(is_free_route(model) for model in models if model)


def effective_execution_model(configured_model: str | None) -> str | None:
    return _campaign_model.get() or configured_model


@contextlib.contextmanager
def scoped_execution_policy(
    execution_policy: str, *, campaign_model_name: str | None = None
) -> Iterator[None]:
    with scoped_campaign_mode(execution_policy == CAMPAIGN):
        selected = _campaign_model.get()
        if selected is None and execution_policy == CAMPAIGN:
            selected = campaign_model_name
        token = _campaign_model.set(selected)
        try:
            yield
        finally:
            _campaign_model.reset(token)


def resolve_execution_policy(request: Request, interview: dict[str, Any] | None = None) -> str:
    """Campaign policy derives monotonically from trusted persisted state,
    never caller-controlled identity headers.
    """
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
