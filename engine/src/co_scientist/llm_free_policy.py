"""Admission policy for campaign requests and system-default free routes."""

import asyncio
import contextlib
import os
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

import litellm

from co_scientist.exceptions import FreeModelEligibilityError
from co_scientist.llm_free_catalog import (
    PROMOTIONAL_FREE_MODELS,
    current_catalog,
    verify_model,
)

FREE_MODE_ENV = "COSCIENTIST_REQUIRE_FREE_MODELS"
_API_BASE = "https://openrouter.ai/api/v1"
_REQUEST_FIELDS = {
    "model",
    "messages",
    "max_tokens",
    "temperature",
    "drop_params",
    "timeout",
    "api_key",
    "api_base",
    "extra_body",
    "response_format",
    "reasoning_effort",
    "tools",
    "tool_choice",
    "stream",
    "stream_options",
}
_BODY_FIELDS = {"provider", "models", "reasoning"}
_campaign_mode: ContextVar[bool] = ContextVar("campaign_mode", default=False)


def campaign_free_mode() -> bool:
    """Return whether every campaign request requires zero-cost admission."""
    configured = os.getenv(FREE_MODE_ENV, "0").strip().lower()
    if configured not in {"0", "false", "", "1", "true"}:
        raise FreeModelEligibilityError("zero-cost mode setting is invalid")
    return _campaign_mode.get() or configured in {"1", "true"}


@contextlib.contextmanager
def scoped_campaign_mode(enabled: bool) -> Iterator[None]:
    """Scope campaign free-model admission to the current task.

    The scope is monotone: nested callers can enable campaign mode but cannot
    weaken an already-active campaign scope.
    """
    token = _campaign_mode.set(_campaign_mode.get() or enabled)
    try:
        yield
    finally:
        _campaign_mode.reset(token)


def _requires_free(args: dict[str, Any], byok: bool) -> bool:
    model = str(args.get("model", ""))
    return campaign_free_mode() or (
        not byok
        and (
            ":free" in model
            or model.removeprefix("openrouter/") in PROMOTIONAL_FREE_MODELS
        )
    )


def _request_body(args: dict[str, Any]) -> dict[str, Any]:
    if litellm.model_fallbacks or litellm.model_alias_map:
        raise FreeModelEligibilityError(
            "zero-cost SDK routing overrides are unqualified"
        )
    if args.keys() - _REQUEST_FIELDS:
        raise FreeModelEligibilityError(
            "zero-cost request contains unqualified options"
        )
    if args.get("api_base", _API_BASE) != _API_BASE:
        raise FreeModelEligibilityError(
            "zero-cost request uses an unverified endpoint"
        )
    body = args.get("extra_body", {})
    if not isinstance(body, dict) or body.keys() - _BODY_FIELDS:
        raise FreeModelEligibilityError(
            "zero-cost request contains plugins or unqualified routing"
        )
    _verify_messages(args.get("messages", []))
    _verify_tools(args.get("tools", []))
    return body


def _object_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(
        isinstance(item, dict) for item in value
    ):
        raise FreeModelEligibilityError(
            "zero-cost request requires a list of objects"
        )
    return value


def _verify_messages(messages: Any) -> None:
    for message in _object_list(messages):
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise FreeModelEligibilityError(
                "zero-cost request contains non-text input"
            )
        if message.keys() - {
            "role",
            "content",
            "tool_calls",
            "tool_call_id",
            "name",
            "reasoning_content",
            "reasoning",
            "reasoning_details",
        }:
            raise FreeModelEligibilityError(
                "zero-cost message contains unqualified fields"
            )


def _verify_tools(tools: Any) -> None:
    for tool in _object_list(tools):
        if tool.get("type") != "function" or set(tool) != {"type", "function"}:
            raise FreeModelEligibilityError(
                "zero-cost request contains a server tool"
            )


def _routes(args: dict[str, Any], body: dict[str, Any]) -> list[str]:
    primary = args.get("model", "")
    if not isinstance(primary, str) or not primary.startswith("openrouter/"):
        raise FreeModelEligibilityError("zero-cost requests require OpenRouter")
    fallbacks = body.get("models", [])
    if not isinstance(fallbacks, list) or not all(
        isinstance(m, str) for m in fallbacks
    ):
        raise FreeModelEligibilityError("zero-cost fallback list is invalid")
    return [primary.removeprefix("openrouter/"), *fallbacks]


async def enforce_free_request(
    args: dict[str, Any], *, byok: bool = False
) -> bool:
    """Validate routes before transport and attach binding zero-price ceilings.

    Campaign mode overrides BYOK. Outside it, the caller supplies credential
    provenance explicitly; a deployment key in kwargs is not a BYOK signal.
    """
    if not _requires_free(args, byok):
        return False
    body = _request_body(args)
    routes = _routes(args, body)
    catalog = await asyncio.to_thread(current_catalog)
    for model in routes:
        verify_model(model, catalog)
    raw_provider = body.get("provider", {})
    if not isinstance(raw_provider, dict):
        raise FreeModelEligibilityError(
            "zero-cost provider options must be an object"
        )
    provider = dict(raw_provider)
    provider["max_price"] = {
        "prompt": 0,
        "completion": 0,
        "request": 0,
    }
    provider["require_parameters"] = True
    args["extra_body"] = {**body, "provider": provider}
    # Pin the transport too: an environment-level proxy/base override must
    # not send an OpenRouter-qualified route to a different billing service.
    args["api_base"] = _API_BASE
    return True
