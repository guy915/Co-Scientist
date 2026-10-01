"""The budget-escalation ladder, driven through plain ``call_llm``.

Split from ``test_llm_budget_escalation.py`` on size. That file pins the
ladder's classification and rung sequence through ``call_llm_json``; these
tests exist because the production failure this ladder answers was a
*direct* ``call_llm`` caller (literature-review synthesis) that got exactly
one attempt and no way to recover. They mirror
``test_escalating_recovers_the_call`` and
``test_disabling_thinking_recovers_a_thinking_only_call`` in that file, but
through ``call_llm``'s own escalation loop
(``llm.attempts.text_retry.run_with_budget_escalation``) rather than
``call_llm_json``'s, to pin that ``call_llm`` actually recovers and not just
that it classifies failures correctly (already covered there).

Reuses that file's network-fake helpers rather than a second
implementation of the same fakes.
"""

from typing import Any

import pytest

from co_scientist.constants import (
    BUDGET_ESCALATION_MAX_TOKENS,
    THINKING_FLOOR_MAX_TOKENS,
)
from co_scientist.exceptions import LLMBudgetExhaustedError
from co_scientist.llm import CompletionSpec, call_llm
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_wrapper_fakes import make_completion as _completion
from tests._llm_wrapper_fakes import make_message as _message
from tests.test_llm_budget_escalation import (
    _MODEL,
    _exhausted,
    _record_acompletion,
    _thinking_only,
)


async def test_call_llm_recovers_on_a_raised_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plain ``call_llm``, budget-exhausted on attempt 1, answers on attempt 2.

    Fails against the pre-fix ``call_llm``, which made exactly one attempt
    and raised ``LLMBudgetExhaustedError`` immediately -- see
    ``test_budget_exhaustion_is_its_own_error`` in the ladder-classification
    file for that behavior.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch,
        [
            _exhausted(THINKING_FLOOR_MAX_TOKENS),
            _completion(_message("the text")),
        ],
    )

    result = await call_llm(
        "a prompt",
        CompletionSpec(model_name=_MODEL, max_tokens=8000),
        max_attempts=5,
    )

    assert result == "the text"
    assert len(calls) == 2
    assert calls[1]["max_tokens"] == BUDGET_ESCALATION_MAX_TOKENS
    thinking = [call["extra_body"]["thinking"]["type"] for call in calls]
    assert thinking == ["enabled", "enabled"]


async def test_call_llm_recovers_with_thinking_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plain ``call_llm`` recovers a thinking-only attempt 1 with thinking off.

    Fails against the pre-fix ``call_llm`` the same way as the budget-raise
    case above -- see ``test_thinking_without_answering_is_its_own_error``.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch,
        [_thinking_only(1149), _completion(_message("the text"))],
    )

    result = await call_llm(
        "a prompt",
        CompletionSpec(model_name=_MODEL),
        max_attempts=5,
    )

    assert result == "the text"
    assert len(calls) == 2
    thinking = [call["extra_body"]["thinking"]["type"] for call in calls]
    assert thinking == ["enabled", "disabled"]


async def test_call_llm_default_max_attempts_exhausts_the_ladder_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default makes exactly the 3 attempts that walk the whole ladder.

    The ladder has three rungs that change the request -- the original
    call, RAISED_BUDGET, then NO_THINKING (see
    ``llm.attempts.escalation.BudgetEscalation``) -- so three attempts is the
    point past which every further attempt would resend the identical
    NO_THINKING request. ``call_llm_json`` keeps a default of 5 because a
    schema or parse failure holds its current rung and genuinely benefits
    from asking again; plain ``call_llm`` has neither failure kind, so its
    default must stop where the ladder does.
    """
    _disable_cache(monkeypatch)
    calls = _record_acompletion(
        monkeypatch, [_exhausted(THINKING_FLOOR_MAX_TOKENS)]
    )

    with pytest.raises(LLMBudgetExhaustedError):
        await call_llm("a prompt", CompletionSpec(model_name=_MODEL))

    assert len(calls) == 3
    thinking = [call["extra_body"]["thinking"]["type"] for call in calls]
    assert thinking == ["enabled", "enabled", "disabled"]


async def test_call_llm_caches_the_escalated_result_under_the_original_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A call that only succeeds after escalating still populates its cache key.

    ``call_llm`` must cache under the caller's original (unescalated) request
    -- mirroring ``call_llm_json``'s ``_cache_validated_result``, which caches
    under ``ctx.spec.max_tokens`` rather than whatever rung finally answered.
    Otherwise a call that always needs escalation would never populate the
    cache key its own future calls look up under: the second call here would
    re-run the whole (failing-then-escalating) ladder instead of hitting the
    cache in one lookup.
    """
    import co_scientist.cache as cache_mod

    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "true")
    monkeypatch.setenv("COSCIENTIST_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cache_mod, "_global_cache", None)

    calls = _record_acompletion(
        monkeypatch,
        [_exhausted(THINKING_FLOOR_MAX_TOKENS), _completion(_message("ok"))],
    )

    spec = CompletionSpec(model_name=_MODEL, max_tokens=8000)
    first = await call_llm("a prompt", spec, max_attempts=5)
    second = await call_llm("a prompt", spec, max_attempts=5)

    assert first == "ok"
    assert second == "ok"
    assert len(calls) == 2  # not 3: the second call hit the cache

    monkeypatch.setattr(cache_mod, "_global_cache", None)
