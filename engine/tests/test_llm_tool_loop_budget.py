"""A tool-loop turn that spends its whole budget reasoning.

The plain and JSON paths have answered this since production taught them
to: an empty completion is classified by *what would fix it*, and only
budget exhaustion is answered by a different budget. The tool loop was
never taught, and raised one flat ``ValueError`` for every cause -- which
ends the loop on the turn it happens, however many turns are left.

Writing a program is the most reasoning-heavy thing anything here asks a
model for, so this is not a rare shape on that path: a measured
simulation-review turn came back ``finish_reason="length"`` carrying
18000 reasoning tokens, no content and no tool calls, and the whole
simulation returned nothing.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.constants import BUDGET_ESCALATION_MAX_TOKENS
from co_scientist.exceptions import LLMBudgetExhaustedError
from co_scientist.llm import CompletionSpec, ToolLoop, call_llm_with_tools
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_fake import install_fake_backend
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
    make_usage as _usage,
)

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
