"""Every rung answers a budget-exhausted attempt, and the top rungs stop.

``MINIMAL_REASONING_REQUIRED`` is reached only from a refused reasoning
instruction, so the budget ladder never listed it; an answerless attempt
made at that rung must end escalation like the ladder's other top rung,
not fail the call with a ``KeyError``.
"""

import pytest

from co_scientist.exceptions import LLMBudgetExhaustedError
from co_scientist.llm.attempts.escalation import (
    BudgetEscalation,
    escalation_for_error,
)


@pytest.mark.parametrize("rung", list(BudgetEscalation))
def test_a_budget_exhausted_attempt_has_an_answer_at_every_rung(
    rung: BudgetEscalation,
) -> None:
    escalation_for_error(LLMBudgetExhaustedError("spent"), rung)


@pytest.mark.parametrize(
    "rung",
    [BudgetEscalation.NO_THINKING, BudgetEscalation.MINIMAL_REASONING_REQUIRED],
)
def test_the_top_rungs_stop_escalating(rung: BudgetEscalation) -> None:
    assert escalation_for_error(LLMBudgetExhaustedError("spent"), rung) is None
