"""Admission policy for campaign requests and system-default free routes."""

import asyncio
import contextlib
import hashlib
import json
import os
import re
from collections.abc import Iterator
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

import litellm

from co_scientist.exceptions import FreeModelEligibilityError
from co_scientist.llm_free_catalog import current_catalog, verify_model

FREE_MODE_ENV = "COSCIENTIST_REQUIRE_FREE_MODELS"
_API_BASE = "https://openrouter.ai/api/v1"
_GROQ_MODEL = "groq/qwen/qwen3.8-27b"
_GROQ_API_BASE = "https://api.groq.com/openai/v1"
_GROQ_ATTESTATION_ENV = "COSCIENTIST_GROQ_FREE_ZDR_ATTESTATION"
_CLOUDFLARE_MODEL_ID = "@cf/google/gemma-4-26b-a4b-it"
_CLOUDFLARE_MODEL = f"openai/{_CLOUDFLARE_MODEL_ID}"
_CLOUDFLARE_ACCOUNT_ID_ENV = "CLOUDFLARE_ACCOUNT_ID"
_CLOUDFLARE_API_TOKEN_ENV = "CLOUDFLARE_API_TOKEN"
_CLOUDFLARE_FREE_ATTESTATION_ENV = (
    "COSCIENTIST_CLOUDFLARE_WORKERS_FREE_ATTESTATION"
)
# Provisional interface bound; 24k-output calls remain excluded until
# later qualification.
_CLOUDFLARE_MAX_TOKENS = 4096
_CLOUDFLARE_MAX_SCHEMA_BYTES = 32_768
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
_GROQ_REQUEST_FIELDS = {
    "model",
    "messages",
    "max_tokens",
    "temperature",
    "drop_params",
    "timeout",
    "api_key",
    "api_base",
    "response_format",
    "tools",
    "stream",
    "stream_options",
}
# JSON formats are admitted only as bounded, exact interface probes; this
# does not establish that the candidate supports either response mode.
_CLOUDFLARE_REQUEST_FIELDS = {
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
    "tools",
    "tool_choice",
    "stream",
}
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
            or model.startswith("groq/")
            or _CLOUDFLARE_MODEL_ID in model
        )
    )


def _enforce_direct_free_route(args: dict[str, Any]) -> bool | None:
    model = str(args.get("model", ""))
    if model.startswith("groq/"):
        return _enforce_groq_free_request(args)
    if _CLOUDFLARE_MODEL_ID in model:
        return _enforce_cloudflare_free_request(args)
    return None


def _request_body(
    args: dict[str, Any], *, api_base: str = _API_BASE
) -> dict[str, Any]:
    if litellm.model_fallbacks or litellm.model_alias_map:
        raise FreeModelEligibilityError(
            "zero-cost SDK routing overrides are unqualified"
        )
    request_fields = (
        _GROQ_REQUEST_FIELDS if api_base == _GROQ_API_BASE else _REQUEST_FIELDS
    )
    if args.keys() - request_fields:
        raise FreeModelEligibilityError(
            "zero-cost request contains unqualified options"
        )
    _verify_stream_option(args, api_base)
    if args.get("api_base", api_base) != api_base:
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


def _verify_stream_option(args: dict[str, Any], api_base: str) -> None:
    if api_base != _GROQ_API_BASE:
        return
    if "stream" in args and type(args["stream"]) is not bool:
        raise FreeModelEligibilityError(
            "zero-cost request requires a boolean stream option"
        )
    if "stream_options" in args and (
        args.get("stream") is not True
        or args["stream_options"] != {"include_usage": True}
    ):
        raise FreeModelEligibilityError(
            "zero-cost request requires usage-only stream options"
        )


def _verify_groq_attestation(args: dict[str, Any]) -> None:
    key = args.get("api_key")
    if key is not None and not isinstance(key, str):
        raise FreeModelEligibilityError(
            "Groq Free/ZDR attestation is missing or stale"
        )
    key = key or os.getenv("GROQ_API_KEY", "")
    today = datetime.now(timezone.utc).date().isoformat()
    fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest() if key else ""
    if (
        not fingerprint
        or os.getenv(_GROQ_ATTESTATION_ENV) != f"{today}:{fingerprint}"
    ):
        raise FreeModelEligibilityError(
            "Groq Free/ZDR attestation is missing or stale"
        )


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
    direct_route_result = _enforce_direct_free_route(args)
    if direct_route_result is not None:
        return direct_route_result
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


def _enforce_groq_free_request(args: dict[str, Any]) -> bool:
    if args.get("model") != _GROQ_MODEL:
        raise FreeModelEligibilityError(
            "zero-cost request requires the pinned Groq route"
        )
    _request_body(args, api_base=_GROQ_API_BASE)
    _verify_groq_attestation(args)
    args["api_base"] = _GROQ_API_BASE
    return True


def _enforce_cloudflare_free_request(args: dict[str, Any]) -> bool:
    """Admit the one provisional Workers Free route behind a daily attestation.

    The attestation is an operator assertion for today's account configuration;
    it does not verify Cloudflare's plan or remaining daily Neurons.
    """
    account_id, token = _cloudflare_free_credentials()
    api_base = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
    )
    body = _verify_cloudflare_request(args, api_base)
    args["api_key"] = token
    args["api_base"] = api_base
    # The engine normally drops unsupported parameters; qualification must
    # observe a provider rejection instead of silently losing response_format.
    args["drop_params"] = False
    args["extra_body"] = {
        **body,
        "options": {**body.get("options", {}), "rejectIfBusy": True},
    }
    return True


def _cloudflare_free_credentials() -> tuple[str, str]:
    account_id = os.getenv(_CLOUDFLARE_ACCOUNT_ID_ENV, "")
    token = os.getenv(_CLOUDFLARE_API_TOKEN_ENV, "")
    today = datetime.now(timezone.utc).date().isoformat()
    expected_attestation = f"{today}:{account_id}:workers-free"
    if (
        not re.fullmatch(r"[a-fA-F0-9]{32}", account_id)
        or not token
        or os.getenv(_CLOUDFLARE_FREE_ATTESTATION_ENV) != expected_attestation
    ):
        raise FreeModelEligibilityError(
            "Cloudflare Workers Free-plan attestation is missing or stale"
        )
    return account_id, token


def _verify_cloudflare_request(
    args: dict[str, Any], api_base: str
) -> dict[str, Any]:
    if args.get("model") != _CLOUDFLARE_MODEL:
        raise FreeModelEligibilityError(
            "zero-cost request requires the pinned Cloudflare candidate"
        )
    if litellm.model_fallbacks or litellm.model_alias_map:
        raise FreeModelEligibilityError(
            "zero-cost SDK routing overrides are unqualified"
        )
    _verify_cloudflare_request_fields(args, api_base)
    _verify_cloudflare_limits(args)
    _verify_messages(args.get("messages", []))
    _verify_tools(args.get("tools", []))
    _verify_cloudflare_tool_choice(args)
    return _cloudflare_extra_body(args)


def _verify_cloudflare_request_fields(
    args: dict[str, Any], api_base: str
) -> None:
    _verify_cloudflare_response_format(args)
    if args.keys() - _CLOUDFLARE_REQUEST_FIELDS:
        raise FreeModelEligibilityError(
            "zero-cost request contains unqualified options"
        )
    supplied_api_base = args.get("api_base")
    if supplied_api_base is not None and supplied_api_base != api_base:
        raise FreeModelEligibilityError(
            "zero-cost request uses an unverified endpoint"
        )


def _verify_cloudflare_response_format(args: dict[str, Any]) -> None:
    if "response_format" not in args:
        return
    response_format = args["response_format"]
    if not isinstance(response_format, dict):
        raise FreeModelEligibilityError(
            "Cloudflare candidate has no qualified JSON response mode"
        )
    if response_format.get("type") == "json_object":
        if response_format.keys() != {"type"}:
            raise FreeModelEligibilityError(
                "Cloudflare candidate has no qualified JSON response mode"
            )
        return
    _verify_cloudflare_json_schema_format(response_format)


def _verify_cloudflare_json_schema_format(
    response_format: dict[str, Any],
) -> None:
    if response_format.get(
        "type"
    ) != "json_schema" or response_format.keys() != {"type", "json_schema"}:
        raise FreeModelEligibilityError(
            "Cloudflare candidate has no qualified JSON response mode"
        )
    definition = response_format["json_schema"]
    allowed_definition_keys = {"name", "schema", "strict"}
    if (
        not isinstance(definition, dict)
        or not {"name", "schema"} <= definition.keys()
        or definition.keys() - allowed_definition_keys
        or not isinstance(definition.get("name"), str)
        or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", definition["name"]) is None
        or not isinstance(definition.get("schema"), dict)
        or ("strict" in definition and definition["strict"] is not False)
    ):
        raise FreeModelEligibilityError(
            "Cloudflare candidate has no qualified JSON response mode"
        )
    try:
        schema_json = json.dumps(
            definition["schema"], separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise FreeModelEligibilityError(
            "Cloudflare candidate has an invalid JSON schema"
        ) from exc
    if len(schema_json.encode("utf-8")) > _CLOUDFLARE_MAX_SCHEMA_BYTES:
        raise FreeModelEligibilityError(
            "Cloudflare candidate JSON schema exceeds the request bound"
        )


def _verify_cloudflare_limits(args: dict[str, Any]) -> None:
    max_tokens = args.get("max_tokens")
    if (
        type(max_tokens) is not int
        or not 1 <= max_tokens <= _CLOUDFLARE_MAX_TOKENS
    ):
        raise FreeModelEligibilityError(
            "zero-cost request exceeds the Cloudflare output bound"
        )
    if "stream" in args and type(args["stream"]) is not bool:
        raise FreeModelEligibilityError(
            "zero-cost request requires a boolean stream option"
        )


def _cloudflare_extra_body(args: dict[str, Any]) -> dict[str, Any]:
    body = args.get("extra_body", {})
    if body is None:
        body = {}
    if not isinstance(body, dict) or body.keys() - {"options"}:
        raise FreeModelEligibilityError(
            "zero-cost request contains plugins or unqualified routing"
        )
    _verify_cloudflare_busy_option(body.get("options", {}))
    return body


def _verify_cloudflare_busy_option(options: Any) -> None:
    if not isinstance(options, dict) or options.keys() - {"rejectIfBusy"}:
        raise FreeModelEligibilityError(
            "zero-cost request contains plugins or unqualified routing"
        )
    if "rejectIfBusy" in options and options["rejectIfBusy"] is not True:
        raise FreeModelEligibilityError(
            "zero-cost request must reject busy Cloudflare capacity"
        )


def _verify_cloudflare_tool_choice(args: dict[str, Any]) -> None:
    tool_choice = args.get("tool_choice")
    if "tool_choice" in args and (
        not isinstance(tool_choice, str)
        or tool_choice not in {"auto", "none", "required"}
    ):
        raise FreeModelEligibilityError(
            "zero-cost request contains an unqualified tool choice"
        )
