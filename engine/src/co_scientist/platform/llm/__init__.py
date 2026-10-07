"""Lazy exports avoid re-entering foundation modules while half-initialized."""

import importlib
from typing import TYPE_CHECKING, Any

# Keep the supported co_scientist.platform.llm.litellm.acompletion patch seam.
import litellm as litellm

if TYPE_CHECKING:
    from co_scientist.core.metrics import ModelCallStats
    from co_scientist.platform.llm.admission.call_budget import (
        current_run_call_count,
        release_run_call_budget,
        scoped_completion_budget,
        scoped_llm_call_budget,
    )
    from co_scientist.platform.llm.admission.free_policy import (
        api_key_for_model,
        current_api_key,
        enforce_free_request,
        scoped_api_key,
        scoped_zero_cost_admission,
    )
    from co_scientist.platform.llm.attempts.retry import (
        provider_outage_backoff_seconds,
        rate_limited_attempt_count,
    )
    from co_scientist.platform.llm.call import call_llm, call_llm_json
    from co_scientist.platform.llm.profile import ModelProfile, model_profile
    from co_scientist.platform.llm.request.thinking import (
        deepseek_thinking_extra_body,
        effective_max_tokens,
        model_reasons,
        reasoning_effort_args,
    )
    from co_scientist.platform.llm.request.transport import complete_request
    from co_scientist.platform.llm.structured.validate import (
        coerce_json_list,
        parse_tool_loop_json,
    )
    from co_scientist.platform.llm.telemetry import (
        record_call,
        record_deterministic_fallback,
        scoped_telemetry,
        scoped_telemetry_phase,
    )
    from co_scientist.platform.llm.tools.loop import ToolLoop, call_llm_with_tools
    from co_scientist.platform.llm.tools.policy import DEFAULT_TOOL_LOOP_TOKEN_BUDGET
    from co_scientist.platform.llm.values import (
        CompletionSpec,
        LLMCallOptions,
        indexed_prompt_name,
    )

__all__ = [
    "DEFAULT_TOOL_LOOP_TOKEN_BUDGET",
    "CompletionSpec",
    "LLMCallOptions",
    "ModelCallStats",
    "ModelProfile",
    "ToolLoop",
    "api_key_for_model",
    "call_llm",
    "call_llm_json",
    "call_llm_with_tools",
    "coerce_json_list",
    "complete_request",
    "current_api_key",
    "current_run_call_count",
    "deepseek_thinking_extra_body",
    "effective_max_tokens",
    "enforce_free_request",
    "indexed_prompt_name",
    "model_profile",
    "model_reasons",
    "parse_tool_loop_json",
    "provider_outage_backoff_seconds",
    "rate_limited_attempt_count",
    "reasoning_effort_args",
    "record_call",
    "record_deterministic_fallback",
    "release_run_call_budget",
    "scoped_api_key",
    "scoped_completion_budget",
    "scoped_llm_call_budget",
    "scoped_telemetry",
    "scoped_telemetry_phase",
    "scoped_zero_cost_admission",
]

_EXPORTS: dict[str, str] = {
    "effective_max_tokens": "co_scientist.platform.llm.request.thinking",
    "complete_request": "co_scientist.platform.llm.request.transport",
    "scoped_completion_budget": "co_scientist.platform.llm.admission.call_budget",
    "DEFAULT_TOOL_LOOP_TOKEN_BUDGET": "co_scientist.platform.llm.tools.policy",
    "CompletionSpec": "co_scientist.platform.llm.values",
    "LLMCallOptions": "co_scientist.platform.llm.values",
    "ModelCallStats": "co_scientist.core.metrics",
    "ModelProfile": "co_scientist.platform.llm.profile",
    "ToolLoop": "co_scientist.platform.llm.tools.loop",
    "api_key_for_model": "co_scientist.platform.llm.admission.free_policy",
    "call_llm": "co_scientist.platform.llm.call",
    "call_llm_json": "co_scientist.platform.llm.call",
    "call_llm_with_tools": "co_scientist.platform.llm.tools.loop",
    "coerce_json_list": "co_scientist.platform.llm.structured.validate",
    "current_api_key": "co_scientist.platform.llm.admission.free_policy",
    "current_run_call_count": "co_scientist.platform.llm.admission.call_budget",
    "deepseek_thinking_extra_body": "co_scientist.platform.llm.request.thinking",
    "enforce_free_request": "co_scientist.platform.llm.admission.free_policy",
    "indexed_prompt_name": "co_scientist.platform.llm.values",
    "model_profile": "co_scientist.platform.llm.profile",
    "model_reasons": "co_scientist.platform.llm.request.thinking",
    "parse_tool_loop_json": "co_scientist.platform.llm.structured.validate",
    "provider_outage_backoff_seconds": "co_scientist.platform.llm.attempts.retry",
    "rate_limited_attempt_count": "co_scientist.platform.llm.attempts.retry",
    "reasoning_effort_args": "co_scientist.platform.llm.request.thinking",
    "record_call": "co_scientist.platform.llm.telemetry",
    "record_deterministic_fallback": "co_scientist.platform.llm.telemetry",
    "release_run_call_budget": "co_scientist.platform.llm.admission.call_budget",
    "scoped_api_key": "co_scientist.platform.llm.admission.free_policy",
    "scoped_llm_call_budget": "co_scientist.platform.llm.admission.call_budget",
    "scoped_telemetry": "co_scientist.platform.llm.telemetry",
    "scoped_telemetry_phase": "co_scientist.platform.llm.telemetry",
    "scoped_zero_cost_admission": "co_scientist.platform.llm.admission.free_policy",
}


if not TYPE_CHECKING:
    # Hiding __getattr__ from typing prevents misspelled exports from being
    # accepted.

    def __getattr__(name: str) -> Any:
        module = _EXPORTS.get(name)
        if module is None:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        value = getattr(importlib.import_module(module), name)
        globals()[name] = value
        return value
