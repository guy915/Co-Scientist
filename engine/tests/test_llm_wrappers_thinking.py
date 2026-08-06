"""Tests for DeepSeek thinking-mode completion parameters.

Split from ``test_llm_wrappers.py``: covers how
``co_scientist.llm_request._build_completion_args`` maps the thinking
opt-in/opt-out onto DeepSeek's ``thinking`` object and
``reasoning_effort``. Every engine node thinks; the opt-out cases below
cover the seam itself, which no call site uses today.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_wrapper_fakes import (
    make_completion as _completion,
)
from tests._llm_wrapper_fakes import (
    make_message as _message,
)

# --- DeepSeek thinking mode --------------------------------------------------


def test_thinking_enabled_by_default_for_deepseek() -> None:
    """Every DeepSeek call thinks unless a call site opts out."""
    from co_scientist.llm_request import (
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
    from co_scientist.llm_request import (
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


def test_thinking_params_absent_for_non_deepseek_models() -> None:
    """The thinking params are DeepSeek-specific and never sent elsewhere."""
    from co_scientist.llm_request import (
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
    from co_scientist.llm_request import (
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
    from co_scientist.llm_request import (
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
    from co_scientist.llm_request import (
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
    from co_scientist.llm_request import (
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
    import litellm

    from co_scientist.agents.ranking.ranking import (
        _call_matchup_judge,
        _DebateContext,
    )
    from co_scientist.agents.ranking.ranking_debate import _MatchupPrompt
    from tests._state import make_hypothesis

    seen: dict[str, Any] = {}

    async def fake_acompletion(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        seen.update(kwargs)
        return _completion(_message('{"winner": "A"}'))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
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
