from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from typing import TypeVar

from co_scientist.core.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.platform.db.decision_usage import DecisionQuotaExceededError
from co_scientist.platform.llm.decisions.client import SystemOneClient
from co_scientist.platform.llm.decisions.settings import DecisionSettings
from co_scientist.platform.llm.decisions.types import Answer, DecisionResult, Question

T = TypeVar("T")


async def swapped_pair(
    client: SystemOneClient, goal: str, hypothesis_a: str, hypothesis_b: str, question: Question
) -> DecisionResult:
    forward = await client.decide(
        {"goal": goal, "A": hypothesis_a, "B": hypothesis_b}, {"winner": question}
    )
    reverse = await client.decide(
        {"goal": goal, "A": hypothesis_b, "B": hypothesis_a}, {"winner": question}
    )
    return combine_swapped(forward, reverse)


def combine_swapped(forward: DecisionResult, reverse: DecisionResult) -> DecisionResult:
    a, b = forward.answers["winner"], reverse.answers["winner"]
    if any(answer.kind != "choice" or set(answer.probabilities) != {"A", "B"} for answer in (a, b)):
        raise ValueError("pairwise decisions require A/B choices")
    yes = (a.probabilities["A"] + b.probabilities["B"]) / 2
    confidence = min(a.confidence, b.confidence, max(yes, 1 - yes))
    if a.value == b.value:
        confidence = 0
    tokens = (
        forward.input_tokens + reverse.input_tokens
        if forward.input_tokens is not None and reverse.input_tokens is not None
        else None
    )
    answer = Answer("choice", "A" if yes >= 0.5 else "B", confidence, {"A": yes, "B": 1 - yes})
    return DecisionResult(forward.model, {"winner": answer}, tokens, reverse.rate_limits)


async def decision_or_fallback(
    state: str,
    questions: dict[str, Question],
    threshold: float | None,
    accept: Callable[[DecisionResult], T],
    fallback: Callable[[], Awaitable[T]],
    *,
    client: SystemOneClient | None = None,
    decide: Callable[[SystemOneClient], Awaitable[DecisionResult]] | None = None,
) -> T:
    if threshold is None or not math.isfinite(threshold) or not 0 < threshold <= 1:
        return await fallback()
    try:
        active = client or SystemOneClient(DecisionSettings.from_env())
        result = (
            await decide(active) if decide is not None else await active.decide(state, questions)
        )
        if all(answer.confidence >= threshold for answer in result.answers.values()):
            return accept(result)
    except DecisionQuotaExceededError:
        pass
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception:
        pass
    return await fallback()
