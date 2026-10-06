from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.cache import LLMCache
from co_scientist.exceptions import LLMBudgetExhaustedError
from co_scientist.llm import (
    CompletionSpec,
    ToolLoop,
    call_llm_with_tools,
    precall,
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


async def test_a_tool_turn_runs_the_executor_then_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disable_llm_cache(monkeypatch)
    first = make_completion(
        make_message(
            None, tool_calls=[make_tool_call("call-1", "search", '{"q": 1}')]
        )
    )
    first.choices[0].message.reasoning_content = "chain of thought"
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch, [first, make_completion(make_message("final"))], requests
    )
    seen: list[Any] = []

    async def executor(tc: Any) -> dict[str, Any]:
        seen.append(tc)
        return {"role": "tool", "tool_call_id": tc.id, "content": "result"}

    text, history = await call_llm_with_tools(
        "a prompt",
        CompletionSpec(model_name="test-model"),
        ToolLoop(tools=SEARCH_TOOL, executor=executor),
    )

    assert text == "final"
    assert [(tc.id, tc.function.name) for tc in seen] == [("call-1", "search")]
    assert history[0] == {"role": "user", "content": "a prompt"}
    assert history[2] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "result",
    }
    assert history[-1]["content"] == "final"
    # DeepSeek rejects a follow-up turn that drops the prior reasoning.
    assert requests[1]["messages"][1]["reasoning_content"] == "chain of thought"
    assert "reasoning_content" not in history[-1]


async def test_a_failing_executor_does_not_replay_the_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retries cannot span tool execution: side effects and unanswered
    calls would be replayed."""
    disable_llm_cache(monkeypatch)
    patch_acompletion(
        monkeypatch,
        [_asks_for_a_tool("c1"), make_completion(make_message("the answer"))],
    )
    runs: list[str] = []

    async def explodes(tc: Any) -> dict[str, Any]:
        runs.append(tc.id)
        raise LLMBudgetExhaustedError("the executor gave up")

    with pytest.raises(LLMBudgetExhaustedError):
        await call_llm_with_tools(
            "a prompt",
            _SPEC,
            ToolLoop(tools=SEARCH_TOOL, executor=explodes, max_iterations=4),
        )

    assert runs == ["c1"]


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


@pytest.mark.parametrize(
    ("second_contract", "provider_calls"),
    [({"pubmed": {"enabled": False}}, 2), ({"pubmed": {"enabled": True}}, 1)],
    ids=["changed-contract-misses", "identical-contract-hits"],
)
async def test_a_cached_transcript_is_reused_only_for_the_same_tool_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    second_contract: dict[str, Any],
    provider_calls: int,
) -> None:
    """Equal schemas can hide changed tool configuration."""
    cache = LLMCache(cache_dir=str(tmp_path), enabled=True)
    monkeypatch.setattr(precall, "get_cache", lambda: cache)
    state = patch_acompletion(
        monkeypatch,
        [
            make_completion(make_message("answer one")),
            make_completion(make_message("answer two")),
        ],
    )

    for contract in ({"pubmed": {"enabled": True}}, second_contract):
        await call_llm_with_tools(
            "same prompt",
            CompletionSpec(model_name="test-model"),
            ToolLoop(
                tools=SEARCH_TOOL,
                executor=echo_executor,
                tool_contract=contract,
            ),
        )

    assert state["calls"] == provider_calls


async def test_a_truncated_tool_call_is_answered_with_an_error_not_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disable_llm_cache(monkeypatch)
    truncated = make_completion(
        make_message(
            None,
            tool_calls=[make_tool_call("call-1", "search", '{"q": "unfinish')],
        )
    )
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch,
        [truncated, make_completion(make_message("final"))],
        requests,
    )
    seen: list[Any] = []

    async def executor(tc: Any) -> dict[str, Any]:
        seen.append(tc)
        return {"role": "tool", "tool_call_id": tc.id, "content": "result"}

    text, _ = await call_llm_with_tools(
        "a prompt", _SPEC, ToolLoop(tools=SEARCH_TOOL, executor=executor)
    )

    assert text == "final"
    assert seen == []
    resent = requests[1]["messages"]
    assert resent[1]["tool_calls"][0]["function"]["arguments"] == "{}"
    assert resent[2]["tool_call_id"] == "call-1"
    assert "Re-issue the call" in resent[2]["content"]
