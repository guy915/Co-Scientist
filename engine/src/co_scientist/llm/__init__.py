"""LLM dispatch: entry points, value objects and run-scoped contexts.

The one module the rest of the engine, the app and the evaluations call the
model through. Everything outside this package imports from
``co_scientist.llm`` and from nowhere beneath it; ``__all__`` is the whole
interface: three entry points (``call_llm``, ``call_llm_json``,
``call_llm_with_tools``), the value objects they take, and the run-scoped
contexts and counters their callers establish and read.

Layout, lowest layer first. Each layer imports only from those above it in
this list, at the module that defines the name:

* ``values``: ``CompletionSpec``, ``LLMCallOptions``.
* ``admission``: credentials, per-run call budget, free-model policy.
* ``telemetry``: in-memory per-call usage capture.
* ``request``: one provider request and its response (completion
  arguments, timeout ceiling, response format, thinking, gateway routing).
* ``structured``: parse, repair, validate and reshape structured output.
* ``attempts``: one attempt, and the retry loops built on it.
* ``tools``: the tool-calling loop.
* ``call``: ``call_llm`` and ``call_llm_json``.

The interface resolves its names on first access instead of importing the
implementation here. A handful of foundation modules the implementation
itself imports (``cache``, ``models_metrics``, ``workspace``, ``mcp_client``)
read ``current_api_key``, ``campaign_free_mode`` or ``ModelCallStats`` from
this package; an eager import of every entry point from this file would
re-enter them half-initialised, so each name loads only the module that
defines it.
"""

import importlib
from typing import TYPE_CHECKING, Any

# Kept as a module attribute: tests patch the completion boundary via
# "co_scientist.llm.litellm.acompletion", which resolves to this object.
import litellm as litellm

if TYPE_CHECKING:
    from co_scientist.llm.admission.call_budget import (
        current_run_call_count,
        release_run_call_budget,
        scoped_llm_call_budget,
    )
    from co_scientist.llm.admission.credentials import (
        current_api_key,
        scoped_api_key,
    )
    from co_scientist.llm.admission.free_policy import (
        campaign_free_mode,
        enforce_free_request,
        scoped_campaign_mode,
    )
    from co_scientist.llm.attempts.retry import rate_limited_attempt_count
    from co_scientist.llm.call import call_llm, call_llm_json
    from co_scientist.llm.request.gateway_body import (
        deepseek_thinking_extra_body,
    )
    from co_scientist.llm.request.thinking import (
        model_reasons,
        reasoning_effort_args,
    )
    from co_scientist.llm.structured.lists import coerce_json_list
    from co_scientist.llm.structured.validate import parse_tool_loop_json
    from co_scientist.llm.telemetry import (
        ModelCallStats,
        record_call,
        record_deterministic_fallback,
        scoped_telemetry,
        scoped_telemetry_phase,
    )
    from co_scientist.llm.tools.loop import ToolLoop, call_llm_with_tools
    from co_scientist.llm.tools.policy import DEFAULT_TOOL_LOOP_TOKEN_BUDGET
    from co_scientist.llm.values import (
        CompletionSpec,
        LLMCallOptions,
        indexed_prompt_name,
    )

__all__ = [
    "DEFAULT_TOOL_LOOP_TOKEN_BUDGET",
    "CompletionSpec",
    "LLMCallOptions",
    "ModelCallStats",
    "ToolLoop",
    "call_llm",
    "call_llm_json",
    "call_llm_with_tools",
    "campaign_free_mode",
    "coerce_json_list",
    "current_api_key",
    "current_run_call_count",
    "deepseek_thinking_extra_body",
    "enforce_free_request",
    "indexed_prompt_name",
    "model_reasons",
    "parse_tool_loop_json",
    "rate_limited_attempt_count",
    "reasoning_effort_args",
    "record_call",
    "record_deterministic_fallback",
    "release_run_call_budget",
    "scoped_api_key",
    "scoped_campaign_mode",
    "scoped_llm_call_budget",
    "scoped_telemetry",
    "scoped_telemetry_phase",
]

# The module each exported name is defined in. Kept beside ``__all__`` so
# adding to the interface is one edit in one place; the TYPE_CHECKING block
# above gives type checkers the same names.
_EXPORTS: dict[str, str] = {
    "DEFAULT_TOOL_LOOP_TOKEN_BUDGET": "co_scientist.llm.tools.policy",
    "CompletionSpec": "co_scientist.llm.values",
    "LLMCallOptions": "co_scientist.llm.values",
    "ModelCallStats": "co_scientist.llm.telemetry",
    "ToolLoop": "co_scientist.llm.tools.loop",
    "call_llm": "co_scientist.llm.call",
    "call_llm_json": "co_scientist.llm.call",
    "call_llm_with_tools": "co_scientist.llm.tools.loop",
    "campaign_free_mode": "co_scientist.llm.admission.free_policy",
    "coerce_json_list": "co_scientist.llm.structured.lists",
    "current_api_key": "co_scientist.llm.admission.credentials",
    "current_run_call_count": "co_scientist.llm.admission.call_budget",
    "deepseek_thinking_extra_body": "co_scientist.llm.request.gateway_body",
    "enforce_free_request": "co_scientist.llm.admission.free_policy",
    "indexed_prompt_name": "co_scientist.llm.values",
    "model_reasons": "co_scientist.llm.request.thinking",
    "parse_tool_loop_json": "co_scientist.llm.structured.validate",
    "rate_limited_attempt_count": "co_scientist.llm.attempts.retry",
    "reasoning_effort_args": "co_scientist.llm.request.thinking",
    "record_call": "co_scientist.llm.telemetry",
    "record_deterministic_fallback": "co_scientist.llm.telemetry",
    "release_run_call_budget": "co_scientist.llm.admission.call_budget",
    "scoped_api_key": "co_scientist.llm.admission.credentials",
    "scoped_campaign_mode": "co_scientist.llm.admission.free_policy",
    "scoped_llm_call_budget": "co_scientist.llm.admission.call_budget",
    "scoped_telemetry": "co_scientist.llm.telemetry",
    "scoped_telemetry_phase": "co_scientist.llm.telemetry",
}


if not TYPE_CHECKING:
    # Hidden from the type checker, which would otherwise accept any
    # attribute of this package and stop catching a misspelled import.

    def __getattr__(name: str) -> Any:
        """Loads an exported name from the module that defines it, once.

        Args:
            name: The attribute being read.

        Returns:
            The exported object, cached on the package so later reads skip
            this.

        Raises:
            AttributeError: If ``name`` is not part of the interface.
        """
        module = _EXPORTS.get(name)
        if module is None:
            raise AttributeError(
                f"module {__name__!r} has no attribute {name!r}"
            )
        value = getattr(importlib.import_module(module), name)
        globals()[name] = value
        return value
