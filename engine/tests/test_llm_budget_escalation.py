"""Tests for the answerless-response ladder in ``call_llm_json``.

A reasoning model can come back with no answer two ways: it fills the
whole ``max_tokens`` allowance thinking (``finish_reason="length"``), or
it finishes thinking and simply writes nothing (``finish_reason="stop"``
with reasoning tokens spent and zero answer tokens). Production produced
both, and re-sending either unchanged reproduced it on every remaining
attempt, billed in full each time. So the retry loop changes the request
instead -- a raised budget, then thinking off -- and the two shapes enter
that ladder at different rungs. These tests pin which failures escalate,
where each one enters, which failures do not escalate at all, and that
the request going out actually carries the change.

The seam is the same one the rest of the wrapper tests use,
``litellm.acompletion``, patched here with a fake that also records the
kwargs of every call so the budget on the wire can be asserted.

``test_llm_call_text_retry.py`` (split out on size) pins the same ladder
driven through plain ``call_llm`` rather than ``call_llm_json`` -- the
production failure this ladder answers was a direct ``call_llm`` caller
(literature-review synthesis) that got exactly one attempt.
``test_llm_reasoning_mandatory.py`` (also split out on size) pins a third,
adjacent failure: a provider's flat 400 refusal of a disabled-reasoning
request, answered by forcing reasoning back on at minimal effort rather
than resending the identical rejected request.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError

from co_scientist.constants import (
    BUDGET_ESCALATION_MAX_INCREMENT,
    BUDGET_ESCALATION_MAX_TOKENS,
    THINKING_FLOOR_MAX_TOKENS,
)
from co_scientist.exceptions import (
    LLMBudgetExhaustedError,
    LLMThinkingOnlyError,
)
from co_scientist.llm import CompletionSpec, call_llm, call_llm_json
from co_scientist.llm.attempts.escalation import (
    BudgetEscalation,
    escalated_max_tokens,
)
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


def _thinking_only(reasoning: int) -> SimpleNamespace:
    """A completion that reasoned, stopped normally, and wrote no answer."""
    return _completion(
        _message(None),
        usage=_usage(3136, reasoning, reasoning_tokens=reasoning),
        finish_reason="stop",
    )


def _provider_error(reasoning: int) -> SimpleNamespace:
    """A completion OpenRouter aborted mid-stream after some reasoning."""
    return _completion(
        _message(None),
        usage=_usage(3378, reasoning, reasoning_tokens=reasoning),
        finish_reason="error",
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


async def test_thinking_without_answering_is_its_own_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reasoning spent, no answer, stopped normally: a different failure.

    The model chose to stop, so it did not want for room -- production
    spent 1149 tokens of an 18000 budget this way. Classifying it as
    budget exhaustion would answer it with a bigger allowance it never
    needed.
    """
    _disable_cache(monkeypatch)
    _record_acompletion(monkeypatch, [_thinking_only(1149)])

    with pytest.raises(LLMThinkingOnlyError):
        await call_llm("a prompt", CompletionSpec(model_name=_MODEL))


async def test_an_empty_response_with_no_reasoning_stays_ordinary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty answer from a call that never reasoned is a plain hiccup.

    Nothing about the request explains it, so nothing about the request
    should change; a plain retry is the remedy.
    """
    _disable_cache(monkeypatch)
    _record_acompletion(
        monkeypatch,
        [
            _completion(
                _message("   "), usage=_usage(500, 0), finish_reason="stop"
            )
        ],
    )

    with pytest.raises(ValueError) as caught:
        await call_llm("a prompt", CompletionSpec(model_name=_MODEL))
    assert type(caught.value) is ValueError


async def test_a_mid_stream_provider_error_is_not_thinking_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``finish_reason="error"`` is a provider failure, not a chosen stop.

    OpenRouter reports an upstream failure mid-stream this way; the model
    never chose to stop, so this must not be classified (and escalated) as
    a thinking-only response. Every attempt hits the same failure here, so
    the loop exhausts its attempts and the last error surfaces -- what
    matters is which type that is.
    """
    _disable_cache(monkeypatch)
    _record_acompletion(monkeypatch, [_provider_error(519)])

    with pytest.raises(ValueError) as caught:
        await call_llm("a prompt", CompletionSpec(model_name=_MODEL))
    assert not isinstance(caught.value, LLMThinkingOnlyError)
    assert not isinstance(caught.value, LLMBudgetExhaustedError)


async def test_the_failure_log_reports_the_budget_actually_sent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The failure line names the floored budget, not the call site's number.

    An 8000-token call site logging "max_tokens 8000" beside
    "reasoning_tokens=18001" reads as a provider fault. The wire carried
    the floor.

    Captured at WARNING because attempt 1 of ``call_llm``'s own escalation
    loop is a non-final attempt (default ``max_attempts=3``), which logs at
    WARNING rather than ERROR (see ``test_llm_failure_logging``). The
    assertions read the WARNING and ERROR lines of all three attempts
    concatenated, so attempt 1's floored number (this test's target) and
    later attempts' escalated numbers can coexist in the same string --
    the budget reported by attempt 1 is the property under test.
    """
    _disable_cache(monkeypatch)
    _record_acompletion(monkeypatch, [_exhausted(THINKING_FLOOR_MAX_TOKENS)])

    with caplog.at_level("WARNING"), pytest.raises(LLMBudgetExhaustedError):
        await call_llm(
            "a prompt", CompletionSpec(model_name=_MODEL, max_tokens=8000)
        )

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert f"max_tokens {THINKING_FLOOR_MAX_TOKENS}" in logged
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


async def test_a_call_already_sized_at_the_constant_still_gets_more_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rung must not resend a caller's own budget unchanged.

    ``RESEARCH_OVERVIEW_MAX_TOKENS`` sits exactly at
    ``BUDGET_ESCALATION_MAX_TOKENS`` (both 24000), so a raise expressed as
    ``max(max_tokens, BUDGET_ESCALATION_MAX_TOKENS)`` returns 24000 for
    24000: the identical request, billed again on the ``RAISED_BUDGET``
    attempt for nothing. This call site is sized the same way to catch
    exactly that regression.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch, [_exhausted(BUDGET_ESCALATION_MAX_TOKENS)]
    )

    with pytest.raises(LLMBudgetExhaustedError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_MODEL,
                max_tokens=BUDGET_ESCALATION_MAX_TOKENS,
                json_schema=_INT_SCHEMA,
            ),
            max_attempts=3,
        )

    assert len(calls) == 3
    budgets = [call["max_tokens"] for call in calls]
    # Attempt 1 sends the caller's own budget; attempt 2 (RAISED_BUDGET)
    # must send strictly more, not the same number again; attempt 3
    # (NO_THINKING) uses the same raised formula.
    assert budgets[0] == BUDGET_ESCALATION_MAX_TOKENS
    assert budgets[1] > BUDGET_ESCALATION_MAX_TOKENS
    assert budgets[2] == budgets[1]


async def test_thinking_only_skips_straight_to_disabling_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The intermediate rung is skipped: room was never the problem.

    Production ran this failure three attempts deep at identical
    settings. Spending an attempt on a raised budget would only prove
    what the finish reason already said.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(monkeypatch, [_thinking_only(1149)])

    with pytest.raises(LLMThinkingOnlyError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
            max_attempts=3,
        )

    thinking = [call["extra_body"]["thinking"]["type"] for call in calls]
    assert thinking == ["enabled", "disabled", "disabled"]


async def test_disabling_thinking_recovers_a_thinking_only_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once thinking is off the model writes the answer, and the loop ends."""
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch, [_thinking_only(1149), _completion(_message('{"a":2}'))]
    )

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
        max_attempts=5,
    )

    assert result == {"a": 2}
    assert len(calls) == 2
    assert "reasoning_effort" not in calls[1]


async def test_a_provider_error_recovers_without_disabling_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mid-stream provider error is a plain retry, not a ladder rung.

    Unlike a genuine thinking-only response, this must not climb to
    ``NO_THINKING`` -- the provider errored, the model never chose to stop,
    and disabling thinking for a call that needed no such thing would be
    the wrong remedy for every attempt after it.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch, [_provider_error(519), _completion(_message('{"a":3}'))]
    )

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(model_name=_MODEL, json_schema=_INT_SCHEMA),
        max_attempts=5,
    )

    assert result == {"a": 3}
    assert len(calls) == 2
    thinking = [call["extra_body"]["thinking"]["type"] for call in calls]
    assert thinking == ["enabled", "enabled"]


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


# --- the raised-budget formula itself ----------------------------------------


def test_escalated_max_tokens_at_below_at_and_above_the_constant() -> None:
    """Pins the three shapes a caller's own budget can take.

    8000 sits below ``BUDGET_ESCALATION_MAX_TOKENS`` and lands on the
    floor, as it always did. 24000 sits exactly at it -- the case that
    used to no-op -- and must come back strictly larger. 60000 sits above
    both the floor and ``BUDGET_ESCALATION_MAX_INCREMENT``, so the
    increment itself is what caps the raise, at ``max_tokens +
    BUDGET_ESCALATION_MAX_INCREMENT``.
    """
    assert (
        escalated_max_tokens(8000, BudgetEscalation.RAISED_BUDGET)
        == BUDGET_ESCALATION_MAX_TOKENS
        == 24000
    )
    assert (
        escalated_max_tokens(
            BUDGET_ESCALATION_MAX_TOKENS, BudgetEscalation.RAISED_BUDGET
        )
        == 36000
    )
    assert escalated_max_tokens(60000, BudgetEscalation.RAISED_BUDGET) == 84000


def test_a_caller_sized_above_the_floor_is_never_cut_down() -> None:
    """The promise the docstrings make, checked past the constant itself.

    Any budget at or above ``BUDGET_ESCALATION_MAX_TOKENS`` must come back
    strictly larger -- never equal (the old no-op) and never smaller.
    """
    for max_tokens in (
        BUDGET_ESCALATION_MAX_TOKENS,
        BUDGET_ESCALATION_MAX_TOKENS + 1,
        200_000,
    ):
        raised = escalated_max_tokens(
            max_tokens, BudgetEscalation.RAISED_BUDGET
        )
        assert raised > max_tokens
        assert raised <= max_tokens + BUDGET_ESCALATION_MAX_INCREMENT


def test_none_escalation_leaves_the_budget_untouched() -> None:
    """The first attempt is not a rung, so nothing here should apply to it."""
    assert escalated_max_tokens(8000, BudgetEscalation.NONE) == 8000
    assert escalated_max_tokens(60000, BudgetEscalation.NONE) == 60000
