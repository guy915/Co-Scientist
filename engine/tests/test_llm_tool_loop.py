"""Offline contracts for llm tool loop."""

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

# A thinking model, so the thinking kwargs are actually applied and the
# top rung is observable rather than a no-op.
_MODEL = "deepseek/deepseek-v4-flash"


def _record(
    monkeypatch: pytest.MonkeyPatch, responses: list[SimpleNamespace]
) -> list[dict[str, Any]]:
    """Patches acompletion, returning the kwargs of each call made."""
    calls: list[dict[str, Any]] = []
    queue = iter(responses)

    async def fake(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return next(queue)

    install_fake_backend(monkeypatch, fake)
    return calls


def _budget_exhausted() -> SimpleNamespace:
    """A turn that reasoned to its ceiling and wrote nothing."""
    return _completion(
        _message(None),
        usage=_usage(
            prompt_tokens=900, completion_tokens=18000, reasoning_tokens=18000
        ),
        finish_reason="length",
    )


def _thinking_only() -> SimpleNamespace:
    """A turn that stopped normally having written no answer."""
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
    """Drives one loop over queued responses; returns text, history, calls."""
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
        # The model chose to stop, so it never wanted for room; the
        # intermediate rung would spend a whole turn proving that.
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
        """The escalated retry is not charged to the turn budget.

        A turn is for the model's next *step*. Spending steps on a request
        that provably cannot answer would end an investigation with its
        work half done, which is the failure this whole path exists to
        avoid -- so a 2-turn loop still gets its two steps.
        """
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
    """A retry may resend a request; it may never rerun a turn's tools."""

    async def test_a_failing_executor_does_not_replay_the_tools(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The escalation must not span tool execution.

        A local tool is not a question -- it writes files and starts
        commands -- so running a turn's tools twice for one request is a
        side effect the model never asked for. It also strands the first
        assistant turn in the transcript with nothing answering its
        calls, which is the one shape the provider rejects outright.
        Both executors swallow their own exceptions today, so this pins
        the boundary rather than a live bug.
        """
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
    """A different budget is no answer to a different problem."""

    async def test_an_empty_reply_with_no_reasoning_is_not_escalated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An ordinary provider hiccup: nothing about the request was
        # wrong, so changing it would spend more tokens on a problem
        # tokens do not solve.
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
        """Reasoning that ends at the ceiling has no observed length.

        No finite budget is provably enough, so escalation alone could
        spend a whole run on ever-larger walls. Thinking off is the last
        rung, and a wall past it is a failure rather than another rung.
        """
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

        # The rung it was sized at, plus a raised budget, plus thinking
        # off -- and then it stops.
        assert len(calls) == 3


class TestTheTranscript:
    async def test_an_answerless_turn_is_not_resent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It contributed nothing, and an empty assistant turn is junk.

        Left in the history it would be resent on the escalated retry --
        an assistant message with no content and no tool calls, which is
        both noise in the prompt and a shape some providers reject.
        """
        _, history, calls = await _run(
            [_budget_exhausted(), _completion(_message("the answer"))],
            monkeypatch,
        )

        resent = calls[1]["messages"]
        assert all(m.get("content") for m in resent)
        assert [m["role"] for m in history] == ["user", "assistant"]
        assert history[-1]["content"] == "the answer"


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

    The budget runs out and the closing turn answers nothing either, so
    the loop is expected to raise; this asserts the hard cap survives
    both the handoff and the harvest being added in front of it.
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
        ]
        # The closing turn, with nothing to say.
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

    final, history = await call_llm_with_tools(
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

    # Stopped on spend, nowhere near the 50 turns it was allowed.
    assert len([m for m in history if m.get("role") == "assistant"]) < 10
    # And stopping did not throw the spend away: the closing turn is the
    # same fake response with its tool calls no longer offered, so what
    # comes back is its content rather than a raised budget error.
    assert final == fat


def test_the_transcript_estimate_counts_what_is_actually_resent() -> None:
    """Tool calls are billed too, so the estimate cannot ignore them."""
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
    """Reaching a ceiling used to throw away everything the loop bought.

    A simulation that had written a model, run it and read its numbers
    returned no observation at all, and the review fell back to
    imagining the mechanism it had just measured. The tokens were spent
    either way, so the loop buys one closing turn with the tools
    withheld and reports what the model makes of it.
    """
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
    """Withholding them is what makes it closing.

    A model still holding its tools spends the turn calling one, which
    is the state the loop is ending because it can no longer afford.
    """
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
    """The harvest is a recovery, not a way to never fail."""
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
    """A turn count overstates the room whenever spend is what binds.

    Telling a model eleven turns remain when the budget affords two is
    how a loop ends mid-step having been warned.
    """
    from co_scientist.llm.tools.policy import _turns_remaining

    loop = ToolLoop(
        tools=_SEARCH_TOOL,
        executor=_tool_executor,
        max_iterations=24,
        max_prompt_tokens=150_000,
    )
    # 40k characters of transcript is ~10k tokens a turn, and 120k of
    # the budget is already spent: three turns, not the eleven the turn
    # ceiling alone would promise.
    messages = [{"role": "user", "content": "x" * 40_000}]
    assert _turns_remaining(13, 120_000, loop, messages) == 3
    # Never zero: the turn being warned on is itself still available.
    assert _turns_remaining(13, 150_000, loop, messages) == 1


async def test_the_closing_turn_asks_for_an_answer_not_a_next_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stripping the tools is not on its own enough.

    Sent the transcript as it stands, a model mid-investigation carries
    on narrating it. The first closing turn measured against the real
    provider came back with "let me check one more detail" -- a sentence
    about work it could no longer do.
    """
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
    """Whether every call has a result and every result has a call."""
    requested = {
        call["id"] for m in messages for call in m.get("tool_calls") or ()
    }
    answered = {m["tool_call_id"] for m in messages if m.get("role") == "tool"}
    return requested == answered


def test_a_complete_turn_is_left_alone() -> None:
    messages = [_assistant("a"), _result("a")]
    assert normalize_tool_transcript(messages) == messages


def test_a_call_with_no_result_gets_an_aborted_one() -> None:
    # The state an interrupted turn leaves, and the one the provider
    # refuses to accept at all.
    repaired = normalize_tool_transcript([_assistant("a")])
    assert _pairs_up(repaired)
    assert json.loads(repaired[1]["content"]) == ABORTED_RESULT


def test_only_the_missing_results_are_synthesized() -> None:
    repaired = normalize_tool_transcript([_assistant("a", "b"), _result("a")])
    assert _pairs_up(repaired)
    assert [m.get("tool_call_id") for m in repaired[1:]] == ["b", "a"]


def test_the_synthesized_result_sits_beside_its_call() -> None:
    # Providers check the pairing positionally as well as by id, so a
    # repair appended at the end is still a rejected conversation.
    repaired = normalize_tool_transcript(
        [_assistant("a"), {"role": "user", "content": "next"}]
    )
    assert repaired[1]["tool_call_id"] == "a"
    assert repaired[2]["role"] == "user"


def test_a_result_answering_no_call_is_dropped() -> None:
    # What remains when the assistant message was lost rather than its
    # results; it can be paired with nothing.
    repaired = normalize_tool_transcript(
        [{"role": "user", "content": "go"}, _result("ghost")]
    )
    assert repaired == [{"role": "user", "content": "go"}]


def test_the_request_is_kept_rather_than_the_turn_erased() -> None:
    # Dropping the assistant message would be tidier and worse: the
    # model would be free to ask again forever with no record of why
    # the last attempt produced nothing.
    repaired = normalize_tool_transcript([_assistant("a")])
    assert repaired[0]["tool_calls"][0]["id"] == "a"


def test_the_aborted_result_does_not_claim_nothing_happened() -> None:
    # An aborted run_command may have had every effect it was going to
    # have. A model told it did not run would simply repeat it.
    assert "may have run" in ABORTED_RESULT["detail"]


def test_the_input_list_is_not_modified() -> None:
    # It can be a cached value shared with another caller.
    messages = [_assistant("a")]
    normalize_tool_transcript(messages)
    assert len(messages) == 1


def _write(call_id: str, path: str, content: str) -> dict[str, Any]:
    """An assistant turn writing one file whole."""
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
    # The measured cost: one simulation rewrote its model five times and
    # 59% of its transcript was versions of that file that no longer
    # existed, re-sent by every turn after each one.
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
    # Only the arguments go. The id and name stay, because the provider
    # rejects a transcript whose calls and results do not pair up.
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
    # A patch is an edit relative to the file it lands on, so an earlier
    # one is not superseded by a later one in any sense worth relying on.
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
    # Every literature loop, which is why this is safe to run on all of
    # them: no write tool is offered, so there is nothing to elide.
    messages = [{"role": "user", "content": "go"}, _assistant("a")]
    before = json.dumps(messages)
    assert elide_superseded_writes(messages) == 0
    assert json.dumps(messages) == before
