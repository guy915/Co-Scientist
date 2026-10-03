"""Offline contracts for llm wrappers."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist import cache as cache_mod
from co_scientist import prompts as prompts_mod
from co_scientist.cache import LLMCache
from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm,
    call_llm_json,
    call_llm_with_tools,
    precall,
)
from tests._llm_fake import SEARCH_TOOL as _SEARCH_TOOL
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_fake import install_fake_backend
from tests._llm_fake import make_completion as _completion
from tests._llm_fake import make_message as _message
from tests._llm_fake import patch_acompletion as _patch_acompletion

# The real prompt writer, captured at import time -- i.e. before the autouse
# ``_no_prompt_disk_writes`` conftest fixture swaps in its per-test no-op.
_REAL_SAVE_PROMPT_TO_DISK = prompts_mod.save_prompt_to_disk


_LLM_WRAPPERS_INT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
}


# --- call_llm --------------------------------------------------------------
async def test_call_llm_returns_message_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``call_llm`` returns the assistant message content verbatim."""
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("the answer text"))])

    result = await call_llm("a prompt", CompletionSpec(model_name="test-model"))

    assert result == "the answer text"


async def test_call_llm_empty_content_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``call_llm`` raises ``ValueError`` when the model returns empty content.

    The wrapper treats whitespace-only content as empty (``content.strip()``).
    ``max_attempts=1`` keeps this test about the empty-content contract, not
    about the retry ladder (covered by ``test_llm_budget_escalation.py``).
    """
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("   "))])

    with pytest.raises(ValueError, match="None or empty content"):
        await call_llm(
            "a prompt", CompletionSpec(model_name="test-model"), max_attempts=1
        )


async def test_call_llm_invoked_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """``call_llm`` makes exactly one completion call on the happy path."""
    _disable_cache(monkeypatch)
    state = _patch_acompletion(monkeypatch, [_completion(_message("hi"))])

    await call_llm("a prompt", CompletionSpec(model_name="test-model"))

    assert state["calls"] == 1


# --- cache-override scoping (cache.scoped_cache_override) -------------------


async def test_scoped_cache_override_false_skips_get_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task-scoped disable bypasses ``get_cache()`` even for use_cache=True.

    Regression test for the fix to a production bug: a per-generator
    ``enable_cache=False`` used to be applied by mutating
    ``COSCIENTIST_CACHE_ENABLED`` (memoized process-wide by
    ``cache.get_cache()``), so one generator's disabled cache could silently
    disable caching for every other generator in the same process. The fix
    scopes the disable to the current task via
    ``cache.scoped_cache_override`` instead: ``_prepare_llm_call`` must
    consult that per-task override and never even call the memoized
    ``get_cache()`` singleton while it is active.
    """
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
    """With no active scope, the process-default ``get_cache()`` is used.

    Companion to the test above: the per-task override must be opt-in, so a
    call made with no ``scoped_cache_override`` active (the common case)
    keeps consulting the process-wide singleton exactly as before.
    """
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


# --- call_llm_json ---------------------------------------------------------


async def test_call_llm_json_parses_clean_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clean JSON content is parsed into a dict and returned."""
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
    """A ```json fenced response is unwrapped before parsing.

    Fence stripping lives in ``call_llm_json`` (unlike ``attempt_json_repair``),
    so the inner object is recovered on the first attempt.
    """
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
    """A trailing comma is repaired, then the repaired dict passes the schema.

    This drives the schema-injection path (a ``json_schema`` is supplied) and
    the post-repair ``validate_json_schema`` branch in one call. The trailing
    comma is a minor repair, fixed on the first attempt without major repairs.
    """
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
    """Content that never parses surfaces as ``json.JSONDecodeError``.

    With no schema, garbage content fails ``json.loads``, every repair strategy
    returns ``(None, ...)``, schema validation never runs, and the wrapper
    raises ``json.JSONDecodeError`` after exhausting ``max_attempts``. One
    response is reused for both attempts via the queue below.
    """
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
    """Parseable JSON that violates the schema raises ``ValidationError``.

    The content parses cleanly but ``a`` is a string, so schema validation
    fails on every attempt and the wrapper re-raises a ``ValidationError``.
    """
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


# --- prompt debug-artifact saving --------------------------------------------


def _enable_real_prompt_saving(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Restore the real prompt writer and sandbox its output under tmp_path.

    The autouse ``_no_prompt_disk_writes`` conftest fixture no-ops
    ``prompts.save_prompt_to_disk`` for every test; the wrappers resolve the
    writer through the ``prompts`` module at call time, so re-installing the
    real function (captured at module import, before the fixture ran) makes
    the save observable again. ``get_prompt_save_path`` writes to the relative
    ``.coscientist_prompts/<run_id>/`` directory, so chdir-ing into
    ``tmp_path`` keeps the files out of the working tree.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        tmp_path: The pytest per-test temporary directory.
    """
    monkeypatch.setattr(
        prompts_mod, "save_prompt_to_disk", _REAL_SAVE_PROMPT_TO_DISK
    )
    monkeypatch.setenv("COSCIENTIST_SAVE_PROMPTS", "true")
    monkeypatch.chdir(tmp_path)


async def test_call_llm_json_saves_prompt_when_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``call_llm_json`` writes the prompt artifact when prompt_name is given.

    The file lands at ``.coscientist_prompts/<run_id>/<prompt_name>.txt`` and
    carries the prompt content plus the appended metadata block.
    """
    _enable_real_prompt_saving(monkeypatch, tmp_path)
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message('{"a": 1}'))])

    result = await call_llm_json(
        "the review prompt",
        CompletionSpec(model_name="test-model"),
        options=LLMCallOptions(
            run_id="run-1",
            prompt_name="review_batch",
            prompt_metadata={"hypotheses_count": 3},
        ),
    )

    assert result == {"a": 1}
    saved = tmp_path / ".coscientist_prompts" / "run-1" / "review_batch.txt"
    assert saved.exists()
    content = saved.read_text(encoding="utf-8")
    assert content.startswith("the review prompt")
    assert "hypotheses_count: 3" in content


async def test_call_llm_json_does_not_save_without_prompt_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without a prompt_name, ``call_llm_json`` writes no prompt artifact."""
    _enable_real_prompt_saving(monkeypatch, tmp_path)
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message('{"a": 1}'))])

    await call_llm_json(
        "a prompt",
        CompletionSpec(model_name="test-model"),
        options=LLMCallOptions(run_id="run-1"),
    )

    assert not (tmp_path / ".coscientist_prompts").exists()


async def test_call_llm_json_run_id_falls_back_to_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A named prompt with no run_id is saved under the "unknown" directory.

    This is the unified save policy: ``prompt_name`` alone triggers the save;
    a missing ``run_id`` no longer skips it.
    """
    _enable_real_prompt_saving(monkeypatch, tmp_path)
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message('{"a": 1}'))])

    await call_llm_json(
        "a prompt",
        CompletionSpec(model_name="test-model"),
        options=LLMCallOptions(prompt_name="proximity"),
    )

    saved = tmp_path / ".coscientist_prompts" / "unknown" / "proximity.txt"
    assert saved.exists()


async def test_call_llm_saves_prompt_when_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``call_llm`` shares the same save-when-named policy."""
    _enable_real_prompt_saving(monkeypatch, tmp_path)
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("synthesis text"))])

    await call_llm(
        "the synthesis prompt",
        CompletionSpec(model_name="test-model"),
        options=LLMCallOptions(
            run_id="run-2", prompt_name="literature_review_synthesis"
        ),
    )

    saved = (
        tmp_path
        / ".coscientist_prompts"
        / "run-2"
        / "literature_review_synthesis.txt"
    )
    assert saved.exists()
    assert saved.read_text(encoding="utf-8").startswith("the synthesis prompt")


async def test_call_llm_with_tools_saves_prompt_when_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``call_llm_with_tools`` shares the same save-when-named policy."""
    _enable_real_prompt_saving(monkeypatch, tmp_path)
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("done"))])

    async def tool_executor(unused_tc: Any) -> dict[str, Any]:
        return {"role": "tool", "content": ""}

    await call_llm_with_tools(
        "the draft prompt",
        CompletionSpec(model_name="test-model"),
        ToolLoop(tools=_SEARCH_TOOL, executor=tool_executor),
        options=LLMCallOptions(prompt_name="generate_draft_with_tools"),
    )

    saved = (
        tmp_path
        / ".coscientist_prompts"
        / "unknown"
        / "generate_draft_with_tools.txt"
    )
    assert saved.exists()
    assert saved.read_text(encoding="utf-8").startswith("the draft prompt")


# --- DeepSeek thinking mode --------------------------------------------------


def test_thinking_enabled_by_default_for_deepseek() -> None:
    """Every DeepSeek call thinks unless a call site opts out."""
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
    """Opting out disables thinking explicitly and spends no reasoning.

    ``reasoning_effort`` must not survive the opt-out: it would ask the
    provider to size a reasoning budget for a call that does not reason.
    """
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
    """A gateway route states the reasoning tier exactly once.

    The gateway's own ``reasoning`` object already carries ``effort``, so a
    top-level ``reasoning_effort`` beside it is a second copy of the same
    instruction -- and the copy the gateway rejects. litellm refuses it for
    a model whose OpenRouter support map does not list the parameter
    (``UnsupportedParamsError``), which the engine survives only because
    every engine call also passes ``drop_params``. The app's own call sites
    invoke litellm directly and do not, so the redundant field failed the
    contextual safety screen outright and parked runs for human review.
    """
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
    """The thinking params are DeepSeek-specific and never sent elsewhere."""
    from co_scientist.llm.request.completion import (
        CompletionShape,
        _build_completion_args,
    )

    args = _build_completion_args(
        "prompt", "gemini/gemini-2.5-flash", 100, 0.5, CompletionShape()
    )

    assert "extra_body" not in args
    assert "reasoning_effort" not in args


# --- Thinking token floor ----------------------------------------------------


def test_thinking_call_raised_to_the_token_floor() -> None:
    """A thinking call never goes out on an answer-sized budget.

    ``max_tokens`` bounds reasoning plus answer, so a budget sized before
    thinking was switched on lets the chain of thought consume the whole
    allowance and return empty content -- billed in full, then retried.
    """
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
    """The floor only raises: a node that sized itself higher keeps its own.

    The scaled batch budgets (review, evolution) already exceed the floor,
    and clamping them down to it would truncate the answers they were sized
    for -- the exact failure this floor exists to prevent.
    """
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
    """A non-thinking call keeps its budget; there is no reasoning to fund."""
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
    """Models without a thinking mode spend the budget on the answer alone."""
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
    """The O(n^2) tournament judge reasons, like every other engine node.

    Asserted at the litellm seam through the real ``call_llm_json`` ->
    ``call_llm`` chain, so what the provider actually receives is verified
    end to end rather than at the ranking call site alone. This is the
    run's highest-volume call, so a silent regression to a non-thinking
    judge would be a large quality change with no other symptom.
    """
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


# --- Gateway routes ----------------------------------------------------------


def test_a_gateway_route_gets_its_own_reasoning_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gateway normalizes reasoning; the provider's own knob is not it.

    Measured against `openrouter/deepseek/deepseek-v4-flash`: a call
    carrying DeepSeek's ``{"thinking": {"type": "disabled"}}`` came back
    with the whole budget spent on reasoning and empty content -- the
    parameter asking for thinking off is read as asking for it on. That
    fails in the shape AGENTS.md records for an exhausted budget, so it
    reads as a token-budget defect rather than as a wrong parameter, and
    the first casualty is title generation, whose 24-token budget a
    chain of thought consumes entirely.
    """
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
    """Adding a gateway must not change what the first-party call sends."""
    from co_scientist.llm import deepseek_thinking_extra_body

    direct = "deepseek/deepseek-v4-flash"

    assert deepseek_thinking_extra_body(direct, enabled=True) == {
        "thinking": {"type": "enabled"}
    }
    assert deepseek_thinking_extra_body(direct, enabled=False) == {
        "thinking": {"type": "disabled"}
    }


def test_a_model_without_thinking_is_untouched_on_either_route() -> None:
    """The route decides the shape, never whether there is one at all."""
    from co_scientist.llm import deepseek_thinking_extra_body

    assert deepseek_thinking_extra_body("gemini/gemini-2.5-flash") == {}
    assert deepseek_thinking_extra_body("openrouter/openai/gpt-4o") == {}


def test_the_gateway_route_is_pinned_to_hosts_that_honour_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gateway spreads one model over hosts that are not interchangeable.

    Three of them matter here. A host that ignores an unsupported
    parameter makes the reasoning knob advisory, which is the failure this
    route already produced once. Hosts differ by an order of magnitude in
    speed while the default ordering picks on price, so a call can land
    on one serving single digit tokens per second -- measured, the
    slowest of six concurrent calls took 32.9s unconstrained against 7.1s
    constrained, and two calls in the first routed run hit the engine's
    own 600s ceiling outright. And they differ by 6.5x in price, which
    neither ``order`` nor ``preferred_min_throughput`` considers at all,
    so without a ceiling the run cost this project reports bounds nothing
    -- the cap is what makes ``constants.pricing`` an estimate of the
    worst case rather than of one arbitrary host.

    The mechanism guarding the first risk changed since that measurement:
    ``sort: throughput`` picked whichever upstream was fastest *per call*,
    which round-robined consecutive calls across Modal/Friendli/Together
    and is very likely why production's prompt-cache hit rate collapsed
    to 6.9% (against a 33.7% monthly baseline) on 2026-09-04, the day
    with the heaviest repeated-prompt traffic -- a prefix cached on one
    upstream is wasted the instant the next call lands on another. The
    replacement, a fixed ``order`` preference plus a
    ``preferred_min_throughput`` floor (OpenRouter's own documented
    "deprioritize, don't exclude" semantics for a degraded endpoint),
    keeps consecutive calls landing on the same host for the cache's
    sake while still moving off one that has degraded into the "single
    digit tokens per second" shape of the original incident.

    The order named above changed again on 2026-09-05: Modal/Friendli/
    Together were chosen for measured throughput without noticing all
    three price at 2x `z-ai/glm-5.3-flash`'s listed rate, and a
    production run routed there was billed $4.70 for work priced at
    $2.50 headline. The price cap (``_MAX_PRICE_MULTIPLE``, tightened
    from 2.0 to 1.0 in the same change) is what should have caught this
    and did not, because 2.0 was loose enough to admit the 2x tier
    outright. The replacement order -- Z.AI, DeepInfra, Novita, GMICloud
    -- all bill the headline rate; none of their throughput is measured,
    which is exactly the gap ``preferred_min_throughput`` and the env
    override exist to cover without a re-pin.
    """
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
    # The direct route has no gateway to constrain, and must not grow one.
    assert "provider" not in deepseek_thinking_extra_body(
        "deepseek/deepseek-v4-flash"
    )


_LLM_REASONING_MANDATORY_INT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
}

# Not a declared gateway route -- the recovery this ladder
# performs must not depend on the per-model shim in
# ``llm.request.gateway_body._gateway_body`` already knowing to avoid a
# bare disable; it must also save a caller that reaches this 400 some other way
# (a model wrongly believed to honour a disable, or one absent from the table
# entirely).
_UNDECLARED_GATEWAY_MODEL = "openrouter/deepseek/deepseek-v4-flash"


def _reasoning_mandatory_error() -> Exception:
    """A litellm ``BadRequestError`` shaped like OpenRouter's real refusal.

    Verbatim message observed on ``minimax/minimax-m3:free`` during
    production run b82f9162's recovered finalize (2026-09-06 04:39:30
    UTC): every batched entailment call failed this way on both of its
    attempts, because the identical rejected request was simply resent.
    """
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
    """A 400 refusing a disable gets minimal reasoning, not a repeat.

    Before this fix, a raw provider error kept the current rung (see
    ``escalation_for_error``'s catch-all), so the identical rejected
    request went out again on every remaining attempt -- exactly the
    production shape: two attempts, two identical 400s, then the
    deterministic fallback.
    """
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
    # Funded like any other thinking call, not left at the caller's
    # answer-sized budget -- see the "floor is not a guarantee" gotcha.
    assert calls[1]["max_tokens"] >= THINKING_FLOOR_MAX_TOKENS
    assert calls[1]["max_tokens"] > calls[0]["max_tokens"]


async def test_a_second_mandatory_reasoning_refusal_still_terminates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider that rejects minimal reasoning too does not loop forever.

    The recovery rung is entered once; a repeat of the same 400 at that
    rung must exhaust the attempt budget normally rather than escalating
    forever or resending the same request unbounded.
    """
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
    # The rung holds rather than escalating further or reverting.
    assert calls[2]["extra_body"]["reasoning"] == {
        "enabled": True,
        "effort": "low",
    }


# ``_NEMO`` is a declared gateway route with
# ``reasoning_can_disable=False``, so a disable request never reaches the
# wire as a literal ``{"enabled": False}`` at all -- it goes out as minimal
# reasoning from the very first attempt (see
# ``llm.request.gateway_body._gateway_body``), unlike
# ``_UNDECLARED_GATEWAY_MODEL`` above, which has to be rejected once before
# the ladder redirects it. This
# is the shape production run 323ff72c (2026-09-06 06:57 UTC) actually hit:
# no 400, just a first attempt that reasoned ~20-21k tokens against an
# 18000-token floor and answered nothing.
_NEMO = "openrouter/minimax/minimax-m3:free"


async def test_a_declared_mandatory_reasoning_model_caps_its_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model that never disables is asked to bound its chain of thought.

    Raising the budget was tried first and lost: production run 323ff72c
    measured ~20-21k reasoning tokens against an 18000-token floor, and
    run 6760ce63 measured 24547 (then 25424) against the 24000-token
    floor that answered it -- each raise met by a proportionally longer
    chain of thought. The request now carries the bound itself, and the
    budget returns to the ordinary thinking floor.
    """
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
    """A cap the provider ignores is still a budget failure the ladder owns.

    Nothing here can make a host honour the bound, so the ordinary
    escalation must still apply -- and its rungs must differ from one
    another. At the retired 24000 floor they did not: a 12000-token
    caller was floored to 24000 on attempt 1, and
    ``escalated_max_tokens`` floors at the same 24000, so all three
    attempts sent the identical request.
    """
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

    # Three attempts made, no more -- the ladder terminates rather than
    # retrying forever once every rung has been tried.
    assert len(calls) == 3
    budgets = [call["max_tokens"] for call in calls]
    assert budgets[0] == THINKING_FLOOR_MAX_TOKENS
    assert budgets[1] == BUDGET_ESCALATION_MAX_TOKENS
    assert budgets[1] > budgets[0]


async def test_a_rejected_reasoning_cap_falls_back_to_the_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host that will not take the bound gets the tier instead of a 400.

    The bound is unverified against every host the free chain's ``models``
    array can land on, so its rejection must degrade rather than fail the
    call -- the same requirement the mandatory-reasoning refusal above
    already established. The recovery rung sends the tier name alone,
    which is the request shape that has actually been served in
    production.
    """
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
    """The cap-rejection match must not swallow the ladder's own failures.

    A budget-exhausted error's own message names ``reasoning_tokens`` and
    ``max_tokens`` -- the two words a loose match for "the provider
    rejected the reasoning bound" would look for -- so a loose match
    would divert every budget failure to the terminal recovery rung and
    retire the escalation ladder.
    """
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
