from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.constants import BUDGET_ESCALATION_MAX_TOKENS
from co_scientist.exceptions import LLMBudgetExhaustedError
from co_scientist.llm import CompletionSpec, ToolLoop, call_llm_with_tools
from co_scientist.llm.tools.policy import _handoff_iteration
from co_scientist.llm.tools.transcript import (
    ABORTED_RESULT,
    elide_superseded_writes,
    normalize_tool_transcript,
)
from tests._llm_fake import SEARCH_TOOL as _SEARCH_TOOL
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_fake import install_fake_backend
from tests._llm_fake import make_completion as _completion
from tests._llm_fake import make_message as _message
from tests._llm_fake import make_tool_call as _tool_call
from tests._llm_fake import make_usage as _usage
from tests._llm_fake import patch_acompletion as _patch_acompletion

# A thinking model makes the last recovery rung observable.
_MODEL = "deepseek/deepseek-v4-flash"


def _record(
    monkeypatch: pytest.MonkeyPatch, responses: list[SimpleNamespace]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    queue = iter(responses)

    async def fake(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return next(queue)

    install_fake_backend(monkeypatch, fake)
    return calls


def _budget_exhausted() -> SimpleNamespace:
    return _completion(
        _message(None),
        usage=_usage(
            prompt_tokens=900, completion_tokens=18000, reasoning_tokens=18000
        ),
        finish_reason="length",
    )


def _thinking_only() -> SimpleNamespace:
    return _completion(
        _message(None),
        usage=_usage(
            prompt_tokens=900, completion_tokens=1149, reasoning_tokens=1149
        ),
        finish_reason="stop",
    )


async def _executor(tc: Any) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": tc.id, "content": "result"}


async def _run(
    responses: list[SimpleNamespace],
    monkeypatch: pytest.MonkeyPatch,
    max_iterations: int = 4,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    _disable_cache(monkeypatch)
    calls = _record(monkeypatch, responses)
    text, history = await call_llm_with_tools(
        prompt="a prompt",
        spec=CompletionSpec(model_name=_MODEL, max_tokens=8000),
        loop=ToolLoop(
            tools=_SEARCH_TOOL,
            executor=_executor,
            max_iterations=max_iterations,
        ),
    )
    return text, history, calls


class TestItIsAnsweredWithADifferentRequest:
    async def test_budget_exhaustion_is_resent_at_a_raised_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, _, calls = await _run(
            [_budget_exhausted(), _completion(_message("the answer"))],
            monkeypatch,
        )

        assert len(calls) == 2
        assert calls[1]["max_tokens"] > calls[0]["max_tokens"]
        assert calls[1]["max_tokens"] >= BUDGET_ESCALATION_MAX_TOKENS

    async def test_a_thinking_only_turn_goes_straight_to_thinking_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, _, calls = await _run(
            [_thinking_only(), _completion(_message("the answer"))],
            monkeypatch,
        )

        assert len(calls) == 2
        assert calls[0]["reasoning_effort"] is not None
        assert calls[1].get("reasoning_effort") is None

    async def test_the_loop_carries_on_where_it_left_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        text, _, calls = await _run(
            [
                _completion(
                    _message(
                        None, tool_calls=[_tool_call("c1", "search", "{}")]
                    )
                ),
                _budget_exhausted(),
                _completion(_message("what the tool showed")),
            ],
            monkeypatch,
            max_iterations=2,
        )

        assert text == "what the tool showed"
        assert len(calls) == 3


class TestTheLadderStopsShortOfTheTools:
    async def test_a_failing_executor_does_not_replay_the_tools(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Retries cannot span tool execution: side effects and unanswered
        calls would be replayed."""
        _disable_cache(monkeypatch)
        _record(
            monkeypatch,
            [
                _completion(
                    _message(
                        None, tool_calls=[_tool_call("c1", "search", "{}")]
                    )
                ),
                _completion(_message("the answer")),
            ],
        )
        runs: list[str] = []

        async def _explodes(tc: Any) -> dict[str, Any]:
            runs.append(tc.id)
            raise LLMBudgetExhaustedError("the executor gave up")

        with pytest.raises(LLMBudgetExhaustedError):
            await call_llm_with_tools(
                prompt="a prompt",
                spec=CompletionSpec(model_name=_MODEL, max_tokens=8000),
                loop=ToolLoop(
                    tools=_SEARCH_TOOL, executor=_explodes, max_iterations=4
                ),
            )

        assert runs == ["c1"]


class TestWhatIsNotEscalated:
    async def test_an_empty_reply_with_no_reasoning_is_not_escalated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Transport hiccups need retries, not larger token budgets.
        _disable_cache(monkeypatch)
        calls = _record(
            monkeypatch,
            [_completion(_message(None), finish_reason="stop")] * 3,
        )

        with pytest.raises(ValueError):
            await call_llm_with_tools(
                prompt="a prompt",
                spec=CompletionSpec(model_name=_MODEL, max_tokens=8000),
                loop=ToolLoop(
                    tools=_SEARCH_TOOL, executor=_executor, max_iterations=4
                ),
            )

        assert len(calls) == 3
        assert len({call["max_tokens"] for call in calls}) == 1

    async def test_the_ladder_ends_rather_than_climbing_forever(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ceiling-exhausted reasoning has no observed upper bound; the final
        rung must terminate."""
        _disable_cache(monkeypatch)
        calls = _record(monkeypatch, [_budget_exhausted() for _ in range(6)])

        with pytest.raises(ValueError):
            await call_llm_with_tools(
                prompt="a prompt",
                spec=CompletionSpec(model_name=_MODEL, max_tokens=8000),
                loop=ToolLoop(
                    tools=_SEARCH_TOOL, executor=_executor, max_iterations=4
                ),
            )

        assert len(calls) == 3


class TestTheTranscript:
    async def test_an_answerless_turn_is_not_resent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty assistant messages add no information and some providers
        reject them."""
        _, history, calls = await _run(
            [_budget_exhausted(), _completion(_message("the answer"))],
            monkeypatch,
        )

        resent = calls[1]["messages"]
        assert all(m.get("content") for m in resent)
        assert [m["role"] for m in history] == ["user", "assistant"]
        assert history[-1]["content"] == "the answer"


def test_no_handoff_when_the_budget_is_too_small_to_warn() -> None:
    assert _handoff_iteration(3) == -1
    assert _handoff_iteration(1) == -1


def test_handoff_lands_at_four_fifths_of_the_budget() -> None:
    assert _handoff_iteration(5) == 4
    assert _handoff_iteration(10) == 8
    assert _handoff_iteration(20) == 16


async def _tool_executor(tc: Any) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": tc.id, "content": "result"}


async def _run_exhausting_loop(
    monkeypatch: pytest.MonkeyPatch, max_iterations: int
) -> None:
    """A failed closing turn must not weaken the hard spend ceiling."""
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
        ]
        + [_completion(_message(""))],
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
    return [
        m
        for m in history
        if m.get("role") == "user"
        and "tool-calling turn(s) left" in str(m.get("content", ""))
    ]


async def test_the_hard_cap_still_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _run_exhausting_loop(monkeypatch, 5)


async def test_handoff_is_injected_once_and_warns_of_the_remaining_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    max_iterations = 5
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
    assert "1 tool-calling turn(s) left" in handoffs[0]["content"]


async def test_no_handoff_turn_on_a_short_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    """Growing transcripts make turn counts insufficient to bound token
    spend."""
    _disable_cache(monkeypatch)
    fat = "x" * 40_000
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

    final, history = await call_llm_with_tools(
        prompt="a prompt",
        spec=CompletionSpec(model_name="test/model", max_tokens=100),
        loop=ToolLoop(
            tools=_SEARCH_TOOL,
            executor=_tool_executor,
            max_iterations=50,
            max_prompt_tokens=60_000,
        ),
    )

    assert len([m for m in history if m.get("role") == "assistant"]) < 10
    assert final == fat


def test_the_transcript_estimate_counts_what_is_actually_resent() -> None:
    from co_scientist.llm.tools.policy import transcript_tokens

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


async def test_running_out_of_room_returns_the_work_rather_than_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paid-for work must survive a ceiling via one closing turn without
    tools."""
    _disable_cache(monkeypatch)
    responses = [
        _completion(
            _message(None, tool_calls=[_tool_call(f"call-{i}", "search", "{}")])
        )
        for i in range(4)
    ]
    responses.append(_completion(_message("what I got as far as")))
    _patch_acompletion(monkeypatch, responses)

    final, _ = await call_llm_with_tools(
        prompt="a prompt",
        spec=CompletionSpec(model_name="test/model", max_tokens=100),
        loop=ToolLoop(
            tools=_SEARCH_TOOL, executor=_tool_executor, max_iterations=4
        ),
    )

    assert final == "what I got as far as"


async def test_the_closing_turn_is_asked_without_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keeping tools would let the model spend the closing turn on another
    unaffordable action."""
    _disable_cache(monkeypatch)
    sent: list[dict[str, Any]] = []
    responses = [
        _completion(
            _message(None, tool_calls=[_tool_call("call-0", "search", "{}")])
        ),
        _completion(_message("done")),
    ]
    _patch_acompletion(monkeypatch, responses, recorder=sent)

    await call_llm_with_tools(
        prompt="a prompt",
        spec=CompletionSpec(model_name="test/model", max_tokens=100),
        loop=ToolLoop(
            tools=_SEARCH_TOOL, executor=_tool_executor, max_iterations=1
        ),
    )

    assert "tools" in sent[0]
    assert "tools" not in sent[-1]


async def test_a_closing_turn_that_answers_nothing_still_fails_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    _patch_acompletion(
        monkeypatch,
        [
            _completion(
                _message(
                    None, tool_calls=[_tool_call("call-0", "search", "{}")]
                )
            ),
            _completion(_message("")),
        ],
    )

    with pytest.raises(RuntimeError, match="exhausted its budget"):
        await call_llm_with_tools(
            prompt="a prompt",
            spec=CompletionSpec(model_name="test/model", max_tokens=100),
            loop=ToolLoop(
                tools=_SEARCH_TOOL, executor=_tool_executor, max_iterations=1
            ),
        )


def test_the_wrap_up_promises_only_the_turns_the_budget_affords() -> None:
    """Advertised turns must fit the remaining spend or the model starts
    unaffordable work."""
    from co_scientist.llm.tools.policy import _turns_remaining

    loop = ToolLoop(
        tools=_SEARCH_TOOL,
        executor=_tool_executor,
        max_iterations=24,
        max_prompt_tokens=150_000,
    )
    messages = [{"role": "user", "content": "x" * 40_000}]
    assert _turns_remaining(13, 120_000, loop, messages) == 3
    assert _turns_remaining(13, 150_000, loop, messages) == 1


async def test_the_closing_turn_asks_for_an_answer_not_a_next_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an answer instruction, a tool-free model can keep narrating
    work it cannot do."""
    _disable_cache(monkeypatch)
    sent: list[dict[str, Any]] = []
    _patch_acompletion(
        monkeypatch,
        [
            _completion(
                _message(
                    None, tool_calls=[_tool_call("call-0", "search", "{}")]
                )
            ),
            _completion(_message("what I found")),
        ],
        recorder=sent,
    )

    await call_llm_with_tools(
        prompt="a prompt",
        spec=CompletionSpec(model_name="test/model", max_tokens=100),
        loop=ToolLoop(
            tools=_SEARCH_TOOL, executor=_tool_executor, max_iterations=1
        ),
    )

    closing = str(sent[-1]["messages"][-1]["content"])
    assert "final turn" in closing
    assert "do not propose further steps" in closing.lower()


def _assistant(*ids: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "run_command", "arguments": "{}"},
            }
            for call_id in ids
        ],
    }


def _result(call_id: str) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": "run_command",
        "content": "{}",
    }


def _pairs_up(messages: list[dict[str, Any]]) -> bool:
    requested = {
        call["id"] for m in messages for call in m.get("tool_calls") or ()
    }
    answered = {m["tool_call_id"] for m in messages if m.get("role") == "tool"}
    return requested == answered


def test_a_complete_turn_is_left_alone() -> None:
    messages = [_assistant("a"), _result("a")]
    assert normalize_tool_transcript(messages) == messages


def test_a_call_with_no_result_gets_an_aborted_one() -> None:
    repaired = normalize_tool_transcript([_assistant("a")])
    assert _pairs_up(repaired)
    assert json.loads(repaired[1]["content"]) == ABORTED_RESULT


def test_only_the_missing_results_are_synthesized() -> None:
    repaired = normalize_tool_transcript([_assistant("a", "b"), _result("a")])
    assert _pairs_up(repaired)
    assert [m.get("tool_call_id") for m in repaired[1:]] == ["b", "a"]


def test_the_synthesized_result_sits_beside_its_call() -> None:
    # Providers require positional call/result pairing; end-appended repairs
    # still fail.
    repaired = normalize_tool_transcript(
        [_assistant("a"), {"role": "user", "content": "next"}]
    )
    assert repaired[1]["tool_call_id"] == "a"
    assert repaired[2]["role"] == "user"


def test_a_result_answering_no_call_is_dropped() -> None:
    repaired = normalize_tool_transcript(
        [{"role": "user", "content": "go"}, _result("ghost")]
    )
    assert repaired == [{"role": "user", "content": "go"}]


def test_the_request_is_kept_rather_than_the_turn_erased() -> None:
    # Dropping unanswered calls loses the failure history and can invite
    # indefinite repetition.
    repaired = normalize_tool_transcript([_assistant("a")])
    assert repaired[0]["tool_calls"][0]["id"] == "a"


def test_the_aborted_result_does_not_claim_nothing_happened() -> None:
    # An aborted command may already have had side effects; never imply it did
    # not run.
    assert "may have run" in ABORTED_RESULT["detail"]


def test_the_input_list_is_not_modified() -> None:
    # A cached transcript may be shared with another caller.
    messages = [_assistant("a")]
    normalize_tool_transcript(messages)
    assert len(messages) == 1


def _write(call_id: str, path: str, content: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": path, "content": content}),
                },
            }
        ],
    }


def test_an_overwritten_file_stops_being_resent() -> None:
    messages = [
        _write("a", "model.py", "first" * 400),
        _write("b", "model.py", "second" * 400),
    ]
    assert elide_superseded_writes(messages) == 1
    first = messages[0]["tool_calls"][0]["function"]["arguments"]
    assert "first" not in first
    assert "superseded" in first
    assert "second" in messages[1]["tool_calls"][0]["function"]["arguments"]


def test_the_call_stays_answerable_after_its_text_goes() -> None:
    # Retain call ids and names so provider-required call/result pairing
    # survives.
    messages = [_write("a", "model.py", "x"), _write("b", "model.py", "y")]
    elide_superseded_writes(messages)
    call = messages[0]["tool_calls"][0]
    assert call["id"] == "a"
    assert call["function"]["name"] == "write_file"
    assert json.loads(call["function"]["arguments"])["path"] == "model.py"


def test_a_different_file_is_not_superseded() -> None:
    messages = [_write("a", "model.py", "keep"), _write("b", "plot.py", "y")]
    assert elide_superseded_writes(messages) == 0
    assert "keep" in messages[0]["tool_calls"][0]["function"]["arguments"]


def test_a_patch_is_left_alone() -> None:
    # A later patch does not supersede an earlier relative edit.
    patch = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "a",
                "function": {"name": "apply_patch", "arguments": "*** patch"},
            }
        ],
    }
    assert elide_superseded_writes([patch, dict(patch)]) == 0


def test_a_loop_with_no_writes_is_untouched() -> None:
    messages = [{"role": "user", "content": "go"}, _assistant("a")]
    before = json.dumps(messages)
    assert elide_superseded_writes(messages) == 0
    assert json.dumps(messages) == before
