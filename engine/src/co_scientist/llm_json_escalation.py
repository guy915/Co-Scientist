"""Budget escalation for the ``call_llm_json`` retry loop.

What a retry *changes about the request* after an attempt came back with
no answer: the ladder of rungs, and the call spec each rung sends. Which
failures escalate, and how far, is the retry loop's own decision and stays
in ``llm_json_retry`` -- which re-exports every name here, so
``co_scientist.llm_json_retry`` remains one import path for the whole
retry surface.
"""

import dataclasses
import enum
from dataclasses import dataclass
from typing import Any

from co_scientist.constants import BUDGET_ESCALATION_MAX_TOKENS


class BudgetEscalation(enum.Enum):
    """How far a retry has escalated after a budget-exhausted attempt.

    A call that came back with no answer -- because it reasoned until it
    hit its ceiling, or because it stopped after reasoning and wrote
    nothing -- does the same thing again if the request does not change.
    Production saw both shapes burn every attempt they were given, each
    one paid for in full, so an answerless attempt moves up this ladder
    instead of being re-sent:

    * ``NONE``: the call as its node sized it.
    * ``RAISED_BUDGET``: resent at ``BUDGET_ESCALATION_MAX_TOKENS``, in
      case the chain of thought was close to finishing.
    * ``NO_THINKING``: resent with thinking off, which removes the
      unbounded side of the budget altogether.

    The last rung is what makes the ladder terminate: reasoning ends at
    the ceiling, so its natural length is unknown and no finite budget is
    provably enough. Escalation is one-way within a call and never leaves
    the retry loop -- the node's own budget is unchanged for the next
    call.
    """

    NONE = "none"
    RAISED_BUDGET = "raised_budget"
    NO_THINKING = "no_thinking"


_ESCALATION_LADDER: dict[BudgetEscalation, BudgetEscalation] = {
    BudgetEscalation.NONE: BudgetEscalation.RAISED_BUDGET,
    BudgetEscalation.RAISED_BUDGET: BudgetEscalation.NO_THINKING,
    BudgetEscalation.NO_THINKING: BudgetEscalation.NO_THINKING,
}


@dataclass(frozen=True)
class _JsonCallSpec:
    """Bundles the model/token/schema fields shared by json-attempt helpers.

    Deliberately credential-free: the effective bring-your-own-key is
    scoped into the task context by ``call_llm_json`` before the retry
    loop starts, so attempts resolve it without carrying it here.
    """

    model_name: str
    max_tokens: int
    temperature: float
    json_schema: dict[str, Any] | None


def escalated_spec(
    spec: _JsonCallSpec, escalation: BudgetEscalation
) -> _JsonCallSpec:
    """The call spec to send at a given escalation rung.

    Raises the budget rather than replacing it, so a node that already
    sized itself above ``BUDGET_ESCALATION_MAX_TOKENS`` is not cut down by
    the very step meant to give it room.

    Args:
        spec: The call spec as the node sized it.
        escalation: The rung this attempt is being made at.

    Returns:
        ``spec`` unchanged at ``NONE``, otherwise a copy with the raised
        budget. Whether thinking is also disabled is the caller's to apply
        -- it is a completion option, not part of the spec.
    """
    if escalation is BudgetEscalation.NONE:
        return spec
    return dataclasses.replace(
        spec, max_tokens=max(spec.max_tokens, BUDGET_ESCALATION_MAX_TOKENS)
    )
