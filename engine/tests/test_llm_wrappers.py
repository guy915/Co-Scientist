from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist import cache as cache_mod
from co_scientist.cache import LLMCache
from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm,
    call_llm_json,
    precall,
)
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_fake import install_fake_backend
from tests._llm_fake import make_completion as _completion
from tests._llm_fake import make_message as _message
from tests._llm_fake import patch_acompletion as _patch_acompletion

_LLM_WRAPPERS_INT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
}


async def test_call_llm_returns_message_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("the answer text"))])

    result = await call_llm("a prompt", CompletionSpec(model_name="test-model"))

    assert result == "the answer text"


async def test_call_llm_empty_content_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("   "))])

    with pytest.raises(ValueError, match="None or empty content"):
        await call_llm(
            "a prompt", CompletionSpec(model_name="test-model"), max_attempts=1
        )


async def test_call_llm_invoked_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _disable_cache(monkeypatch)
    state = _patch_acompletion(monkeypatch, [_completion(_message("hi"))])

    await call_llm("a prompt", CompletionSpec(model_name="test-model"))

    assert state["calls"] == 1


async def test_scoped_cache_override_false_skips_get_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"get_cache": 0}

    def _tracking_get_cache() -> LLMCache:
        calls["get_cache"] += 1
        return LLMCache(enabled=True)

    monkeypatch.setattr(precall, "get_cache", _tracking_get_cache)
    _patch_acompletion(monkeypatch, [_completion(_message("fresh"))])

    with cache_mod.scoped_cache_override(False):
        result = await call_llm(
            "a prompt",
            CompletionSpec(model_name="test-model"),
            options=LLMCallOptions(use_cache=True),
        )

    assert result == "fresh"
    assert calls["get_cache"] == 0


async def test_no_scoped_override_still_uses_get_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"get_cache": 0}

    def _tracking_get_cache() -> LLMCache:
        calls["get_cache"] += 1
        return LLMCache(enabled=False)

    monkeypatch.setattr(precall, "get_cache", _tracking_get_cache)
    _patch_acompletion(monkeypatch, [_completion(_message("fresh"))])

    await call_llm(
        "a prompt",
        CompletionSpec(model_name="test-model"),
        options=LLMCallOptions(use_cache=True),
    )

    assert calls["get_cache"] == 1


async def test_call_llm_json_parses_clean_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    _patch_acompletion(
        monkeypatch, [_completion(_message('{"a": 1, "b": "x"}'))]
    )

    result = await call_llm_json(
        "a prompt", CompletionSpec(model_name="test-model")
    )

    assert result == {"a": 1, "b": "x"}


async def test_call_llm_json_strips_markdown_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    fenced = '```json\n{"a": 7}\n```'
    _patch_acompletion(monkeypatch, [_completion(_message(fenced))])

    result = await call_llm_json(
        "a prompt", CompletionSpec(model_name="test-model")
    )

    assert result == {"a": 7}


async def test_call_llm_json_repairs_trailing_comma_and_validates_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message('{"a": 1,}'))])

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(
            model_name="test-model", json_schema=_LLM_WRAPPERS_INT_SCHEMA
        ),
        max_attempts=2,
    )

    assert result == {"a": 1}


async def test_call_llm_json_unparseable_raises_json_decode_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    garbage = _completion(_message("this is not json at all"))
    _patch_acompletion(monkeypatch, [garbage, garbage])

    with pytest.raises(json.JSONDecodeError):
        await call_llm_json(
            "a prompt", CompletionSpec(model_name="test-model"), max_attempts=2
        )


async def test_call_llm_json_schema_mismatch_raises_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jsonschema.exceptions import ValidationError

    _disable_cache(monkeypatch)
    bad = _completion(_message('{"a": "not an int"}'))
    _patch_acompletion(monkeypatch, [bad, bad])

    with pytest.raises(ValidationError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name="test-model", json_schema=_LLM_WRAPPERS_INT_SCHEMA
            ),
            max_attempts=2,
        )


def test_thinking_enabled_by_default_for_deepseek() -> None:
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    args = _build_completion_args(
        "prompt", "deepseek/deepseek-v4-flash", 100, 0.5, CompletionShape()
    )

    assert args["extra_body"] == {"thinking": {"type": "enabled"}}
    assert args["reasoning_effort"] == "high"


def test_thinking_disabled_drops_reasoning_effort() -> None:
    """Do not ask for reasoning sizing after explicitly disabling it."""
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    args = _build_completion_args(
        "prompt",
        "deepseek/deepseek-v4-flash",
        100,
        0.5,
        CompletionShape(enable_thinking=False),
    )

    assert args["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in args


def test_gateway_route_carries_the_effort_only_inside_extra_body() -> None:
    """Duplicating the knob at top level causes unsupported-parameter
    failures."""
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    args = _build_completion_args(
        "prompt",
        "openrouter/deepseek/deepseek-v4-flash",
        100,
        0.5,
        CompletionShape(),
    )

    assert args["extra_body"]["reasoning"] == {
        "enabled": True,
        "effort": "high",
    }
    assert "reasoning_effort" not in args


def test_thinking_params_absent_for_non_deepseek_models() -> None:
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    args = _build_completion_args(
        "prompt", "gemini/gemini-2.5-flash", 100, 0.5, CompletionShape()
    )

    assert "extra_body" not in args
    assert "reasoning_effort" not in args


def test_thinking_call_raised_to_the_token_floor() -> None:
    """Reasoning and the answer share the provider's max_tokens budget."""
    from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    args = _build_completion_args(
        "prompt", "deepseek/deepseek-v4-flash", 4000, 0.5, CompletionShape()
    )

    assert args["max_tokens"] == THINKING_FLOOR_MAX_TOKENS


def test_token_floor_never_lowers_a_larger_budget() -> None:
    """Batch callers can require a larger answer budget than the common
    floor."""
    from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    above_floor = THINKING_FLOOR_MAX_TOKENS + 6000
    args = _build_completion_args(
        "prompt",
        "deepseek/deepseek-v4-flash",
        above_floor,
        0.5,
        CompletionShape(),
    )

    assert args["max_tokens"] == above_floor


def test_token_floor_not_applied_when_thinking_is_off() -> None:
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    args = _build_completion_args(
        "prompt",
        "deepseek/deepseek-v4-flash",
        4000,
        0.5,
        CompletionShape(enable_thinking=False),
    )

    assert args["max_tokens"] == 4000


def test_token_floor_not_applied_to_non_thinking_models() -> None:
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    args = _build_completion_args(
        "prompt", "gemini/gemini-2.5-flash", 4000, 0.5, CompletionShape()
    )

    assert args["max_tokens"] == 4000


async def test_ranking_matchup_thinks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.agents.ranking.ranking_debate import (
        _call_matchup_judge,
        _DebateContext,
        _MatchupPrompt,
    )
    from tests._state import make_hypothesis

    seen: dict[str, Any] = {}

    async def fake_acompletion(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        seen.update(kwargs)
        return _completion(_message('{"winner": "A"}'))

    install_fake_backend(monkeypatch, fake_acompletion)
    _disable_cache(monkeypatch)

    mp = _MatchupPrompt("compare A and B", None, None, None)
    ctx = _DebateContext(
        make_hypothesis(text="a"),
        make_hypothesis(text="b"),
        "goal",
        "deepseek/deepseek-v4-flash",
    )
    await _call_matchup_judge(mp, ctx)

    assert seen["extra_body"] == {"thinking": {"type": "enabled"}}
    assert seen["reasoning_effort"] == "high"


def test_a_gateway_route_gets_its_own_reasoning_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The direct DeepSeek disable knob is interpreted as thinking-on by the
    gateway."""
    monkeypatch.delenv("COSCIENTIST_GATEWAY_PROVIDER_ORDER", raising=False)
    from co_scientist.llm import deepseek_thinking_extra_body

    routed = "openrouter/deepseek/deepseek-v4-flash"

    gateway = {
        "require_parameters": True,
        "allow_fallbacks": True,
        "preferred_min_throughput": 25,
        "order": ["z-ai", "deepinfra", "novita", "gmicloud"],
        "max_price": {"prompt": 0.083 * 1.05, "completion": 0.165 * 1.05},
    }

    assert deepseek_thinking_extra_body(routed, enabled=False) == {
        "reasoning": {"enabled": False},
        "provider": gateway,
    }
    assert deepseek_thinking_extra_body(routed, enabled=True) == {
        "reasoning": {"enabled": True, "effort": "high"},
        "provider": gateway,
    }


def test_the_direct_route_still_speaks_deepseek() -> None:
    from co_scientist.llm import deepseek_thinking_extra_body

    direct = "deepseek/deepseek-v4-flash"

    assert deepseek_thinking_extra_body(direct, enabled=True) == {
        "thinking": {"type": "enabled"}
    }
    assert deepseek_thinking_extra_body(direct, enabled=False) == {
        "thinking": {"type": "disabled"}
    }


def test_a_model_without_thinking_is_untouched_on_either_route() -> None:
    from co_scientist.llm import deepseek_thinking_extra_body

    assert deepseek_thinking_extra_body("gemini/gemini-2.5-flash") == {}
    assert deepseek_thinking_extra_body("openrouter/openai/gpt-4o") == {}


def test_the_gateway_route_is_pinned_to_hosts_that_honour_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gateway hosts differ in parameter support, price and cache locality."""
    monkeypatch.delenv("COSCIENTIST_GATEWAY_PROVIDER_ORDER", raising=False)
    from co_scientist.llm import deepseek_thinking_extra_body

    body = deepseek_thinking_extra_body("openrouter/deepseek/deepseek-v4-flash")

    assert body["provider"] == {
        "require_parameters": True,
        "allow_fallbacks": True,
        "preferred_min_throughput": 25,
        "order": ["z-ai", "deepinfra", "novita", "gmicloud"],
        "max_price": {"prompt": 0.083 * 1.05, "completion": 0.165 * 1.05},
    }
    assert "provider" not in deepseek_thinking_extra_body(
        "deepseek/deepseek-v4-flash"
    )


_LLM_REASONING_MANDATORY_INT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
}

# An undeclared model tests recovery independently of the per-model redirect.
_UNDECLARED_GATEWAY_MODEL = "openrouter/deepseek/deepseek-v4-flash"


def _reasoning_mandatory_error() -> Exception:
    from litellm.exceptions import BadRequestError

    return BadRequestError(
        message=(
            'OpenrouterException - {"error":{"message":"Reasoning is '
            'mandatory for this endpoint and cannot be disabled.",'
            '"code":400,"metadata":{"provider_name":null}}}'
        ),
        model=_UNDECLARED_GATEWAY_MODEL,
        llm_provider="openrouter",
    )


async def test_a_mandatory_reasoning_refusal_recovers_on_the_next_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeating an identical disable refusal cannot recover; minimal
    reasoning can."""
    _disable_cache(monkeypatch)
    calls: list[dict[str, Any]] = []

    async def fake_acompletion(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        if len(calls) == 1:
            raise _reasoning_mandatory_error()
        return _completion(_message('{"a": 1}'))

    install_fake_backend(monkeypatch, fake_acompletion)

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(
            model_name=_UNDECLARED_GATEWAY_MODEL,
            max_tokens=6000,
            json_schema=_LLM_REASONING_MANDATORY_INT_SCHEMA,
        ),
        max_attempts=3,
        options=LLMCallOptions(enable_thinking=False),
    )

    assert result == {"a": 1}
    assert len(calls) == 2
    assert calls[0]["extra_body"]["reasoning"] == {"enabled": False}
    assert calls[1]["extra_body"]["reasoning"] == {
        "enabled": True,
        "effort": "low",
    }
    # Recovery still needs room for reasoning plus the answer.
    assert calls[1]["max_tokens"] >= THINKING_FLOOR_MAX_TOKENS
    assert calls[1]["max_tokens"] > calls[0]["max_tokens"]


async def test_a_second_mandatory_reasoning_refusal_still_terminates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery must stay within the configured attempt budget."""
    _disable_cache(monkeypatch)
    calls: list[dict[str, Any]] = []

    async def fake_acompletion(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        raise _reasoning_mandatory_error()

    install_fake_backend(monkeypatch, fake_acompletion)

    from litellm.exceptions import BadRequestError

    with pytest.raises(BadRequestError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_UNDECLARED_GATEWAY_MODEL,
                max_tokens=6000,
                json_schema=_LLM_REASONING_MANDATORY_INT_SCHEMA,
            ),
            max_attempts=3,
            options=LLMCallOptions(enable_thinking=False),
        )

    assert len(calls) == 3
    assert calls[0]["extra_body"]["reasoning"] == {"enabled": False}
    assert calls[1]["extra_body"]["reasoning"] == {
        "enabled": True,
        "effort": "low",
    }
    assert calls[2]["extra_body"]["reasoning"] == {
        "enabled": True,
        "effort": "low",
    }


# Declared mandatory-reasoning models request minimal reasoning immediately.
# They can exhaust the reasoning floor without returning an answer.
_NEMO = "openrouter/minimax/minimax-m3:free"


async def test_a_declared_mandatory_reasoning_model_caps_its_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raising the budget can buy more thought instead of room for an answer."""
    from co_scientist.constants import MINIMAL_REASONING_MAX_TOKENS

    _disable_cache(monkeypatch)
    calls: list[dict[str, Any]] = []

    async def fake_acompletion(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return _completion(_message('{"a": 1}'))

    install_fake_backend(monkeypatch, fake_acompletion)

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(
            model_name=_NEMO,
            max_tokens=12000,
            json_schema=_LLM_REASONING_MANDATORY_INT_SCHEMA,
        ),
        max_attempts=3,
        options=LLMCallOptions(enable_thinking=False),
    )

    assert result == {"a": 1}
    assert len(calls) == 1
    assert calls[0]["max_tokens"] == THINKING_FLOOR_MAX_TOKENS
    assert calls[0]["extra_body"]["reasoning"] == {
        "enabled": True,
        "max_tokens": MINIMAL_REASONING_MAX_TOKENS,
    }


async def test_the_ladder_still_terminates_when_the_cap_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Budget recovery still needs distinct bounded rungs when hosts ignore
    the cap."""
    from co_scientist.constants import BUDGET_ESCALATION_MAX_TOKENS
    from co_scientist.exceptions import LLMBudgetExhaustedError
    from tests._llm_fake import make_usage as _usage

    _disable_cache(monkeypatch)
    calls: list[dict[str, Any]] = []

    async def fake_acompletion(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        budget = kwargs["max_tokens"]
        return _completion(
            _message(None),
            usage=_usage(3000, budget, reasoning_tokens=budget),
            finish_reason="length",
        )

    install_fake_backend(monkeypatch, fake_acompletion)

    with pytest.raises(LLMBudgetExhaustedError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_NEMO,
                max_tokens=12000,
                json_schema=_LLM_REASONING_MANDATORY_INT_SCHEMA,
            ),
            max_attempts=3,
            options=LLMCallOptions(enable_thinking=False),
        )

    assert len(calls) == 3
    budgets = [call["max_tokens"] for call in calls]
    assert budgets[0] == THINKING_FLOOR_MAX_TOKENS
    assert budgets[1] == BUDGET_ESCALATION_MAX_TOKENS
    assert budgets[1] > budgets[0]


async def test_a_rejected_reasoning_cap_falls_back_to_the_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsupported bounds can degrade to a reasoning tier instead of failing
    outright."""
    from litellm.exceptions import BadRequestError

    _disable_cache(monkeypatch)
    calls: list[dict[str, Any]] = []

    async def fake_acompletion(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        if len(calls) == 1:
            raise BadRequestError(
                message=(
                    'OpenrouterException - {"error":{"message":"Invalid '
                    "request: reasoning.max_tokens is not supported for "
                    'this model.","code":400}}'
                ),
                model=_NEMO,
                llm_provider="openrouter",
            )
        return _completion(_message('{"a": 1}'))

    install_fake_backend(monkeypatch, fake_acompletion)

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(
            model_name=_NEMO,
            max_tokens=12000,
            json_schema=_LLM_REASONING_MANDATORY_INT_SCHEMA,
        ),
        max_attempts=3,
        options=LLMCallOptions(enable_thinking=False),
    )

    assert result == {"a": 1}
    assert len(calls) == 2
    assert calls[1]["extra_body"]["reasoning"] == {
        "enabled": True,
        "effort": "low",
    }


def test_a_budget_failure_is_not_read_as_a_rejected_cap() -> None:
    """Loose error-word matching would hijack the token escalation ladder."""
    from co_scientist.exceptions import LLMBudgetExhaustedError
    from co_scientist.llm.attempts.escalation import (
        BudgetEscalation,
        escalation_for_error,
    )

    error = LLMBudgetExhaustedError(
        "LLM spent its entire token budget without answering. "
        "Model: openrouter/minimax/minimax-m3:free (finish_reason=length, "
        "max_tokens=24000, reasoning_tokens=24547)"
    )

    assert (
        escalation_for_error(error, BudgetEscalation.NONE)
        is BudgetEscalation.RAISED_BUDGET
    )


def _wire_args(model: str, *, enable_thinking: bool = True) -> dict[str, Any]:
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )
    from co_scientist.llm.request.thinking import apply_provider_constraints

    shape = CompletionShape(enable_thinking=enable_thinking)
    args = _build_completion_args("prompt", model, 4000, 0.5, shape)
    apply_provider_constraints(args, model)
    return args


_DIRECT_THINKING_MODELS = [
    "anthropic/claude-opus-5-5",
    "anthropic/claude-sonnet-5-5",
    "anthropic/claude-fable-5-1",
    "openai/gpt-6.1-sol",
    "openai/gpt-6-luna",
    "gemini/gemini-3.8-flash",
    "gemini/gemini-3.1-pro-preview",
]


@pytest.mark.parametrize("model", _DIRECT_THINKING_MODELS)
@pytest.mark.parametrize("enable_thinking", [True, False])
def test_direct_models_think_at_their_default_effort_within_the_floor(
    model: str, enable_thinking: bool
) -> None:
    """They think by default and that thinking spends the output cap, so even
    calls that ask for no thinking get the floor."""
    args = _wire_args(model, enable_thinking=enable_thinking)

    assert not {"output_config", "reasoning_effort", "thinking"} & args.keys()
    cap = args.get("max_completion_tokens") or args["max_tokens"]
    assert cap >= THINKING_FLOOR_MAX_TOKENS


@pytest.mark.parametrize(
    "model", ["anthropic/claude-opus-5-5", "openai/gpt-6-astra"]
)
def test_models_that_reject_sampling_knobs_never_get_them(model: str) -> None:
    assert "temperature" not in _wire_args(model)


def test_openai_reasoning_models_cap_completion_tokens_by_name() -> None:
    args = _wire_args("openai/gpt-6.1-sol")

    assert "max_tokens" not in args
    assert args["max_completion_tokens"] >= THINKING_FLOOR_MAX_TOKENS


def test_claude_structured_calls_avoid_a_forced_tool_call() -> None:
    """LiteLLM turns a native schema into a forced tool call, which Claude
    refuses while thinking; the schema rides in the prompt instead."""
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    shape = CompletionShape(json_schema={"type": "object"})
    args = _build_completion_args(
        "prompt", "anthropic/claude-opus-5-5", 4000, 0.5, shape
    )

    assert args["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("model", ["openai/gpt-6.1-sol", "openai/gpt-6-astra"])
def test_gpt6_calls_go_through_the_responses_api(model: str) -> None:
    """Chat Completions refuses function calling on these models, and the
    literature drafting loop needs tools."""
    args = _wire_args(model)

    assert args["model"] == model.replace("openai/", "openai/responses/", 1)


def test_a_retried_gpt6_request_is_routed_once() -> None:
    from co_scientist.llm.request.thinking import apply_provider_constraints

    args = _wire_args("openai/gpt-6.1-sol")
    apply_provider_constraints(args, "openai/gpt-6.1-sol")

    assert args["model"] == "openai/responses/gpt-6.1-sol"
