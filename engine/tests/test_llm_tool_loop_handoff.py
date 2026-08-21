"""Tests for the tool loop's near-the-bound wrap-up handoff.

Split from ``test_llm_wrappers_tools.py`` to keep that file's subject the
loop's normal path. The behaviour here is a warning turn injected while the
model still has room to act on it; the hard iteration cap remains the
backstop and is asserted to still fire.
"""

from typing import Any

import pytest

from co_scientist.llm import CompletionSpec, ToolLoop, call_llm_with_tools
from co_scientist.llm_tool_loop import _handoff_iteration
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_wrapper_fakes import (
    SEARCH_TOOL as _SEARCH_TOOL,
)
from tests._llm_wrapper_fakes import (
    make_completion as _completion,
)
from tests._llm_wrapper_fakes import (
    make_message as _message,
)
from tests._llm_wrapper_fakes import (
    make_tool_call as _tool_call,
)
from tests._llm_wrapper_fakes import (
    patch_acompletion as _patch_acompletion,
)


def test_no_handoff_when_the_budget_is_too_small_to_warn() -> None:
    """At 3 turns, 80% is turn 2 -- too early to be a wrap-up signal."""
    assert _handoff_iteration(3) == -1
    assert _handoff_iteration(1) == -1


def test_handoff_lands_at_four_fifths_of_the_budget() -> None:
    assert _handoff_iteration(5) == 4
    assert _handoff_iteration(10) == 8
    assert _handoff_iteration(20) == 16


async def _tool_executor(tc: Any) -> dict[str, Any]:
    """Returns a fixed tool result for any requested call."""
    return {"role": "tool", "tool_call_id": tc.id, "content": "result"}


async def _run_exhausting_loop(
    monkeypatch: pytest.MonkeyPatch, max_iterations: int
) -> None:
    """Drives a loop whose model never stops requesting tools.

    The budget runs out, so the loop is expected to raise; this asserts the
    hard cap survives the handoff being added in front of it.
    """
    _disable_cache(monkeypatch)
    _patch_acompletion(
        monkeypatch,
        [
            _completion(
                _message(
                    None, tool_calls=[_tool_call(f"call-{i}", "search", "{}")]
                )
            )
            for i in range(max_iterations)
        ],
    )

    with pytest.raises(RuntimeError, match="exhausted its budget"):
        await call_llm_with_tools(
            prompt="a prompt",
            spec=CompletionSpec(model_name="test/model", max_tokens=100),
            loop=ToolLoop(
                tools=_SEARCH_TOOL,
                executor=_tool_executor,
                max_iterations=max_iterations,
            ),
        )


def _handoff_turns(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Returns the injected wrap-up turns present in a message history."""
    return [
        m
        for m in history
        if m.get("role") == "user"
        and "tool-calling turn(s) left" in str(m.get("content", ""))
    ]


async def test_the_hard_cap_still_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The handoff makes exhaustion rarer, not impossible."""
    await _run_exhausting_loop(monkeypatch, 5)


async def test_handoff_is_injected_once_and_warns_of_the_remaining_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One wrap-up turn appears, naming how many turns are left."""
    _disable_cache(monkeypatch)
    max_iterations = 5
    # Requests a tool every turn but the last, which answers -- so the loop
    # ends normally *after* the handoff turn has been injected.
    responses = [
        _completion(
            _message(None, tool_calls=[_tool_call(f"call-{i}", "search", "{}")])
        )
        for i in range(max_iterations - 1)
    ]
    responses.append(_completion(_message("final answer")))
    _patch_acompletion(monkeypatch, responses)

    final, history = await call_llm_with_tools(
        prompt="a prompt",
        spec=CompletionSpec(model_name="test/model", max_tokens=100),
        loop=ToolLoop(
            tools=_SEARCH_TOOL,
            executor=_tool_executor,
            max_iterations=max_iterations,
        ),
    )

    assert final == "final answer"
    handoffs = _handoff_turns(history)
    assert len(handoffs) == 1
    # Injected at iteration 4 of a 5-iteration budget, so one turn remains.
    assert "1 tool-calling turn(s) left" in handoffs[0]["content"]


async def test_no_handoff_turn_on_a_short_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 3-turn budget never injects, so a short loop reads unchanged."""
    _disable_cache(monkeypatch)
    responses = [
        _completion(
            _message(None, tool_calls=[_tool_call("call-0", "search", "{}")])
        ),
        _completion(_message("final answer")),
    ]
    _patch_acompletion(monkeypatch, responses)

    _, history = await call_llm_with_tools(
        prompt="a prompt",
        spec=CompletionSpec(model_name="test/model", max_tokens=100),
        loop=ToolLoop(
            tools=_SEARCH_TOOL, executor=_tool_executor, max_iterations=3
        ),
    )
    assert _handoff_turns(history) == []


async def test_a_loop_stops_on_spend_before_it_runs_out_of_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn count cannot bound what a growing transcript costs.

    Every turn re-sends the whole conversation, so spend grows with the
    square of the turn count. On a live extended run nine reflection items
    reached their 14-turn ceiling and re-sent 1.81M prompt tokens between
    them -- 24% of the run's entire input -- for no observation, because
    reaching the ceiling is what failing means. The token ceiling stops
    that case without shortening a loop that is converging cheaply.
    """
    _disable_cache(monkeypatch)
    fat = "x" * 40_000  # ~10k tokens of tool output per turn
    _patch_acompletion(
        monkeypatch,
        [
            _completion(
                _message(
                    fat, tool_calls=[_tool_call(f"call-{i}", "search", "{}")]
                )
            )
            for i in range(50)
        ],
    )

    with pytest.raises(RuntimeError, match="exhausted its budget"):
        await call_llm_with_tools(
            prompt="a prompt",
            spec=CompletionSpec(model_name="test/model", max_tokens=100),
            loop=ToolLoop(
                tools=_SEARCH_TOOL,
                executor=_tool_executor,
                # Far more turns than the spend ceiling will allow.
                max_iterations=50,
                max_prompt_tokens=60_000,
            ),
        )


def test_the_transcript_estimate_counts_what_is_actually_resent() -> None:
    """Tool calls are billed too, so the estimate cannot ignore them."""
    from co_scientist.llm_tool_policy import transcript_tokens

    plain = [{"role": "user", "content": "a" * 400}]
    with_calls = [
        {
            "role": "assistant",
            "content": "a" * 400,
            "tool_calls": [{"id": "c1", "function": {"name": "search"}}],
        }
    ]

    assert transcript_tokens(plain) == 100
    assert transcript_tokens(with_calls) > 100
    assert transcript_tokens([]) == 0
