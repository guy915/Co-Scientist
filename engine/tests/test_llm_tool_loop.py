from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.llm import (
    CompletionSpec,
    ToolLoop,
    call_llm_with_tools,
)
from co_scientist.llm.tools.policy import _turns_remaining
from tests._llm_fake import (
    SEARCH_TOOL,
    disable_llm_cache,
    echo_executor,
    make_completion,
    make_message,
    make_tool_call,
    patch_acompletion,
)

_SPEC = CompletionSpec(model_name="test/model", max_tokens=100)


def _asks_for_a_tool(call_id: str = "call-0") -> SimpleNamespace:
    return make_completion(
        make_message(None, tool_calls=[make_tool_call(call_id, "search", "{}")])
    )


def _loop(max_iterations: int, **overrides: Any) -> ToolLoop:
    return ToolLoop(
        tools=SEARCH_TOOL,
        executor=echo_executor,
        max_iterations=max_iterations,
        **overrides,
    )


@pytest.mark.parametrize(
    ("max_iterations", "tool_turns", "handoffs"),
    [(5, 4, 1), (3, 1, 0)],
    ids=["warned-before-the-cap", "too-short-to-warn"],
)
async def test_the_model_is_warned_once_before_its_turns_run_out(
    monkeypatch: pytest.MonkeyPatch,
    max_iterations: int,
    tool_turns: int,
    handoffs: int,
) -> None:
    disable_llm_cache(monkeypatch)
    patch_acompletion(
        monkeypatch,
        [_asks_for_a_tool(f"call-{i}") for i in range(tool_turns)]
        + [make_completion(make_message("final answer"))],
    )

    final, history = await call_llm_with_tools(
        "a prompt", _SPEC, _loop(max_iterations)
    )

    assert final == "final answer"
    warnings = [
        m
        for m in history
        if m.get("role") == "user"
        and "tool-calling turn(s) left" in str(m.get("content", ""))
    ]
    assert len(warnings) == handoffs
    if handoffs:
        assert "1 tool-calling turn(s) left" in warnings[0]["content"]


async def test_a_loop_stops_on_spend_before_it_runs_out_of_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Growing transcripts make turn counts insufficient to bound token
    spend."""
    disable_llm_cache(monkeypatch)
    fat = "x" * 40_000
    patch_acompletion(
        monkeypatch,
        [
            make_completion(
                make_message(
                    fat,
                    tool_calls=[make_tool_call(f"call-{i}", "search", "{}")],
                )
            )
            for i in range(50)
        ],
    )

    final, history = await call_llm_with_tools(
        "a prompt", _SPEC, _loop(50, max_prompt_tokens=60_000)
    )

    assert len([m for m in history if m.get("role") == "assistant"]) < 10
    assert final == fat


def test_the_wrap_up_promises_only_the_turns_the_budget_affords() -> None:
    """Advertised turns must fit the remaining spend or the model starts
    unaffordable work."""
    loop = _loop(24, max_prompt_tokens=150_000)
    messages = [{"role": "user", "content": "x" * 40_000}]

    assert _turns_remaining(13, 120_000, loop, messages) == 3
    assert _turns_remaining(13, 150_000, loop, messages) == 1


async def test_running_out_of_turns_gets_one_tool_free_closing_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paid-for work must survive a ceiling, and keeping tools would let the
    model spend the closing turn on another unaffordable action."""
    disable_llm_cache(monkeypatch)
    sent: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch,
        [
            *[_asks_for_a_tool(f"call-{i}") for i in range(4)],
            make_completion(make_message("what I got as far as")),
        ],
        recorder=sent,
    )

    final, _ = await call_llm_with_tools("a prompt", _SPEC, _loop(4))

    assert final == "what I got as far as"
    assert all("tools" in request for request in sent[:-1])
    assert "tools" not in sent[-1]
    closing = str(sent[-1]["messages"][-1]["content"])
    assert "final turn" in closing
    assert "do not propose further steps" in closing.lower()


async def test_a_closing_turn_that_answers_nothing_still_fails_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed closing turn must not weaken the hard spend ceiling."""
    disable_llm_cache(monkeypatch)
    patch_acompletion(
        monkeypatch,
        [
            *[_asks_for_a_tool(f"call-{i}") for i in range(5)],
            make_completion(make_message("")),
        ],
    )

    with pytest.raises(RuntimeError, match="exhausted its budget"):
        await call_llm_with_tools("a prompt", _SPEC, _loop(5))
