"""Tests for surviving a provider's "reasoning is mandatory" refusal.

Split out of ``test_llm_budget_escalation.py`` on size. The failure this
covers is adjacent to that ladder but distinct: a provider that flatly
refuses a disabled-reasoning request (a 400, not an empty completion) can
be raised from any rung that sends ``enabled: False`` -- the call's own
first attempt, or the escalation ladder's own ``NO_THINKING`` rung -- and
before this fix the identical rejected request was simply resent on every
remaining attempt, since a raw provider error left the ladder's rung
unchanged. Production hit exactly that shape: every batched entailment
call against ``minimax/minimax-m3:free`` failed on both of its attempts
with "Reasoning is mandatory for this endpoint and cannot be disabled"
(run b82f9162's recovered finalize, 2026-09-06 04:39:30 UTC).
"""

from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS
from co_scientist.llm import CompletionSpec, call_llm_json
from co_scientist.llm_types import LLMCallOptions
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_wrapper_fakes import (
    make_completion as _completion,
)
from tests._llm_wrapper_fakes import (
    make_message as _message,
)

_INT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
}

# Not a declared ``_GATEWAY_MODELS`` entry -- the recovery this ladder
# performs must not depend on the per-model shim in
# ``llm_gateway_body._declared_gateway_body`` already knowing to avoid a bare
# disable; it must also save a caller that reaches this 400 some other way
# (a model wrongly believed to honour a disable, or one absent from the
# table entirely).
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

    monkeypatch.setattr(
        "co_scientist.llm.litellm.acompletion", fake_acompletion
    )

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(
            model_name=_UNDECLARED_GATEWAY_MODEL,
            max_tokens=6000,
            json_schema=_INT_SCHEMA,
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

    monkeypatch.setattr(
        "co_scientist.llm.litellm.acompletion", fake_acompletion
    )

    from litellm.exceptions import BadRequestError

    with pytest.raises(BadRequestError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_UNDECLARED_GATEWAY_MODEL,
                max_tokens=6000,
                json_schema=_INT_SCHEMA,
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


# ``_NEMO`` is declared in ``_GATEWAY_MODELS`` with
# ``reasoning_can_disable=False``, so a disable request never reaches the
# wire as a literal ``{"enabled": False}`` at all -- it goes out as minimal
# reasoning from the very first attempt (see
# ``llm_gateway_body._declared_gateway_body``), unlike
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

    monkeypatch.setattr(
        "co_scientist.llm.litellm.acompletion", fake_acompletion
    )

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(
            model_name=_NEMO, max_tokens=12000, json_schema=_INT_SCHEMA
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
    from tests._llm_wrapper_fakes import make_usage as _usage

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

    monkeypatch.setattr(
        "co_scientist.llm.litellm.acompletion", fake_acompletion
    )

    with pytest.raises(LLMBudgetExhaustedError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name=_NEMO, max_tokens=12000, json_schema=_INT_SCHEMA
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

    monkeypatch.setattr(
        "co_scientist.llm.litellm.acompletion", fake_acompletion
    )

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(
            model_name=_NEMO, max_tokens=12000, json_schema=_INT_SCHEMA
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
    from co_scientist.llm_json_escalation import (
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
