"""Tests for the budget-exhaustion ladder in ``call_llm_json``.

A reasoning model that fills its whole ``max_tokens`` allowance with chain
of thought returns ``finish_reason="length"`` and empty content. Retrying
that request unchanged reproduces it exactly -- in production the same call
burned all five attempts, each billed in full -- so the retry loop answers
it by changing the request: first a raised budget, then thinking off. These
tests pin which failures escalate, which do not, and that the request going
out actually carries the change.

The seam is the same one the rest of the wrapper tests use,
``litellm.acompletion``, patched here with a fake that also records the
kwargs of every call so the budget on the wire can be asserted.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError

from co_scientist.constants import (
    BUDGET_ESCALATION_MAX_TOKENS,
    THINKING_FLOOR_MAX_TOKENS,
)
from co_scientist.exceptions import LLMBudgetExhaustedError
from co_scientist.llm import CompletionSpec, call_llm, call_llm_json
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_wrapper_fakes import (
    make_completion as _completion,
)
from tests._llm_wrapper_fakes import (
    make_message as _message,
)
from tests._llm_wrapper_fakes import (
    make_usage as _usage,
)

_MODEL = "deepseek/deepseek-v4-flash"

_INT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
}


def _exhausted(budget: int) -> SimpleNamespace:
    """A completion that spent ``budget`` tokens reasoning and answered none."""
    return _completion(
        _message(None),
        usage=_usage(500, budget, reasoning_tokens=budget),
        finish_reason="length",
    )


def _record_acompletion(
    monkeypatch: pytest.MonkeyPatch, responses: list[SimpleNamespace]
) -> list[dict[str, Any]]:
    """Patch the completion seam, recording each call's kwargs.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        responses: Completion namespaces to return on successive calls. The
            last one repeats, so a test needs only as many entries as the
            distinct responses it cares about.

    Returns:
        The list the fake appends each call's kwargs to, in call order.
    """
    calls: list[dict[str, Any]] = []

    async def fake_acompletion(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        index = min(len(calls) - 1, len(responses) - 1)
        return responses[index]

    monkeypatch.setattr(
        "co_scientist.llm.litellm.acompletion", fake_acompletion
    )
    return calls


# --- classifying the empty response -----------------------------------------


async def test_budget_exhaustion_is_its_own_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty response at ``finish_reason="length"`` is budget exhaustion."""
    _disable_cache(monkeypatch)
    _record_acompletion(monkeypatch, [_exhausted(THINKING_FLOOR_MAX_TOKENS)])

    with pytest.raises(LLMBudgetExhaustedError):
        await call_llm("a prompt", CompletionSpec(model_name=_MODEL))


async def test_an_empty_answer_that_stopped_normally_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model that stopped on its own and said nothing is a plain failure.

    The production log carried both shapes side by side -- one call ended
    at the ceiling with 18001 reasoning tokens, another stopped normally
    after 1417 and returned a single token. Only the first is answerable
    by a different budget; folding them together would escalate a call
    that a plain retry already recovers.
    """
    _disable_cache(monkeypatch)
    _record_acompletion(
        monkeypatch,
        [
            _completion(
                _message(None),
                usage=_usage(500, 1418, reasoning_tokens=1417),
                finish_reason="stop",
            )
        ],
    )

    with pytest.raises(ValueError) as caught:
        await call_llm("a prompt", CompletionSpec(model_name=_MODEL))
    assert not isinstance(caught.value, LLMBudgetExhaustedError)


async def test_the_failure_log_reports_the_budget_actually_sent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The error line names the floored budget, not the call site's number.

    An 8000-token call site logging "max_tokens: 8000" beside
    "reasoning_tokens=18001" reads as a provider fault. The wire carried
    the floor.
    """
    _disable_cache(monkeypatch)
    _record_acompletion(monkeypatch, [_exhausted(THINKING_FLOOR_MAX_TOKENS)])

    with caplog.at_level("ERROR"), pytest.raises(LLMBudgetExhaustedError):
        await call_llm(
            "a prompt", CompletionSpec(model_name=_MODEL, max_tokens=8000)
        )

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert f"max_tokens: {THINKING_FLOOR_MAX_TOKENS}" in logged
    assert "call site asked for 8000" in logged


# --- the ladder --------------------------------------------------------------


async def test_the_ladder_raises_the_budget_then_drops_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each exhausted attempt changes the next request, in ladder order."""
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch, [_exhausted(THINKING_FLOOR_MAX_TOKENS)]
    )

    with pytest.raises(LLMBudgetExhaustedError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_MODEL, max_tokens=8000, json_schema=_INT_SCHEMA
            ),
            max_attempts=3,
        )

    assert len(calls) == 3
    budgets = [call["max_tokens"] for call in calls]
    assert budgets == [
        THINKING_FLOOR_MAX_TOKENS,
        BUDGET_ESCALATION_MAX_TOKENS,
        BUDGET_ESCALATION_MAX_TOKENS,
    ]
    thinking = [call["extra_body"]["thinking"]["type"] for call in calls]
    assert thinking == ["enabled", "enabled", "disabled"]


async def test_the_top_rung_holds_for_every_further_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Past the last rung the loop stops changing the request, not retrying.

    The ladder is finite and the attempt budget is not spent on it: a
    fourth and fifth attempt still go out, just at the settled rung.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch, [_exhausted(THINKING_FLOOR_MAX_TOKENS)]
    )

    with pytest.raises(LLMBudgetExhaustedError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
            max_attempts=5,
        )

    assert len(calls) == 5
    thinking = [call["extra_body"]["thinking"]["type"] for call in calls]
    assert thinking == ["enabled", "enabled"] + ["disabled"] * 3


async def test_escalating_recovers_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raised budget that lets the answer through ends the loop there."""
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch,
        [
            _exhausted(THINKING_FLOOR_MAX_TOKENS),
            _completion(_message('{"a":1}')),
        ],
    )

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
        max_attempts=5,
    )

    assert result == {"a": 1}
    assert len(calls) == 2
    assert calls[1]["max_tokens"] == BUDGET_ESCALATION_MAX_TOKENS


async def test_a_schema_failure_leaves_the_budget_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only budget exhaustion escalates; a bad answer is answered by feedback.

    Raising the budget for a schema failure would spend more tokens per
    attempt on a problem more tokens do not solve.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch,
        [_completion(_message('{"a": "not an integer"}'))],
    )

    with pytest.raises(ValidationError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
            max_attempts=3,
        )

    budgets = {call["max_tokens"] for call in calls}
    assert budgets == {THINKING_FLOOR_MAX_TOKENS}
