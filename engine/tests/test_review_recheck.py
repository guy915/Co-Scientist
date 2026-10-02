"""A blocked idea gets one recurrent review per run, and never a second.

Deriving the disposition from the whole review record (FIX-4) is inert
unless a *later* verdict can arrive for a blocked idea, and the mature
cascade only runs over ``viable`` ones -- so the run that blocked 20 of
22 ideas would still block 20 of 22. These tests pin the bounded closure:
one recurrent review per blocked hypothesis for the whole run, recorded
on the hypothesis so a checkpoint round trip and a second cycle issue no
further calls, and capped run-wide.

They assert control-flow shape and call counts, never a threshold: the
per-run ceiling is monkeypatched rather than pinned at its value.
"""

from collections import Counter
from typing import Any

import pytest

from co_scientist.agents.reflection import (
    comprehensive_reflection,
    review_recheck,
)
from co_scientist.agents.reflection.comprehensive_reflection import (
    comprehensive_reflection_node,
)
from co_scientist.agents.reflection.review_recheck import (
    RECHECK_REVIEW_TYPE,
    recheck_targets,
)
from co_scientist.agents.reflection.review_types import ReviewType
from co_scientist.models import Hypothesis
from tests._state import make_hypothesis, make_review, make_state


def _blocked(index: int) -> Hypothesis:
    """An idea the initial review gate barred from the tournament."""
    hypothesis = make_hypothesis(
        text=f"blocked idea {index}",
        reviews=[make_review(scores={"scientific_soundness": 2, "novelty": 8})],
    )
    hypothesis.review_disposition = "inaccurate"
    return hypothesis


def _viable(index: int) -> Hypothesis:
    """An idea the initial review gate cleared."""
    hypothesis = make_hypothesis(text=f"viable idea {index}")
    hypothesis.review_disposition = "viable"
    return hypothesis


def _incident_pool() -> list[Hypothesis]:
    """The production pool shape: 20 of 22 ideas blocked by one screen."""
    return [_blocked(i) for i in range(20)] + [_viable(i) for i in range(2)]


class _ReviewStub:
    """Counts mature-review calls per (review type, hypothesis).

    Scoped per hypothesis because the recheck and the cascade's own
    recurrent review are the same review type: an idea a recheck cleared
    earns a genuine recurrent review on a later cycle, and counting the
    two together would read as the recheck re-firing.
    """

    def __init__(self, verdict: str | None) -> None:
        self.verdict = verdict
        self.calls: Counter[tuple[str, str]] = Counter()

    async def __call__(
        self, state: Any, hypothesis: Hypothesis, review_type: ReviewType
    ) -> Any:
        self.calls[(review_type.value, hypothesis.id)] += 1
        result = None if self.verdict is None else {"verdict": self.verdict}
        return comprehensive_reflection._ReviewRun(review_type, result, None)

    def rechecks(self, hypotheses: list[Hypothesis]) -> int:
        """How many recheck calls these hypotheses received."""
        return sum(
            self.calls[(RECHECK_REVIEW_TYPE.value, hypothesis.id)]
            for hypothesis in hypotheses
        )


def _stub_reviews(
    monkeypatch: pytest.MonkeyPatch, verdict: str | None
) -> _ReviewStub:
    """Replace the one seam every mature review call goes through."""
    stub = _ReviewStub(verdict)
    monkeypatch.setattr(comprehensive_reflection, "review_hypothesis", stub)
    return stub


def _state(hypotheses: list[Hypothesis]) -> Any:
    """A state carrying only the pool, so no observation review fires."""
    return make_state(hypotheses=hypotheses, articles_with_reasoning=None)


@pytest.mark.asyncio
async def test_a_recheck_clears_the_ideas_a_deeper_review_finds_sound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 20-of-22 run keeps a real tournament and a real evolution pool."""
    pool = _incident_pool()
    blocked = pool[:20]
    stub = _stub_reviews(monkeypatch, "sound")

    await comprehensive_reflection_node(_state(pool))

    assert stub.rechecks(blocked) == 20
    assert all(hypothesis.is_rankable() for hypothesis in pool)


@pytest.mark.asyncio
async def test_a_second_cycle_issues_no_further_recheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once per hypothesis per run, not once per cycle."""
    pool = _incident_pool()
    blocked = pool[:20]
    stub = _stub_reviews(monkeypatch, "sound")
    state = _state(pool)

    await comprehensive_reflection_node(state)
    first_cycle = stub.rechecks(blocked)
    stub.calls.clear()
    await comprehensive_reflection_node(state)

    assert first_cycle == 20
    assert stub.rechecks(blocked) == 0


@pytest.mark.asyncio
async def test_a_confirmed_block_is_not_rechecked_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The unbounded case: a recheck that changes nothing must not repeat.

    Blocked ideas are exactly the population that grows when the gate
    misfires, so a recheck driven by the disposition alone would re-fire
    on every cycle for every idea it failed to clear.
    """
    pool = _incident_pool()
    blocked = pool[:20]
    stub = _stub_reviews(monkeypatch, "rejected")
    state = _state(pool)

    await comprehensive_reflection_node(state)
    stub.calls.clear()
    await comprehensive_reflection_node(state)

    assert not any(hypothesis.is_rankable() for hypothesis in blocked)
    assert stub.rechecks(blocked) == 0


@pytest.mark.asyncio
async def test_a_failed_recheck_call_still_spends_its_one_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The marker records the attempt, not the answer."""
    pool = [_blocked(0)]
    stub = _stub_reviews(monkeypatch, None)
    state = _state(pool)

    await comprehensive_reflection_node(state)
    await comprehensive_reflection_node(state)

    assert stub.rechecks(pool) == 1


def test_the_recheck_marker_survives_a_checkpoint_round_trip() -> None:
    """A flag held only in memory would re-fire on every run resume."""
    hypothesis = _blocked(0)
    review_recheck.mark_recheck_issued(hypothesis)

    restored = Hypothesis.from_dict(hypothesis.to_dict())

    assert recheck_targets([restored]) == []


def test_the_run_wide_ceiling_bounds_a_pathological_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pool of blocked ideas cannot spend the run's budget on rechecks."""
    monkeypatch.setattr(review_recheck, "MAX_RECHECKS_PER_RUN", 3)
    pool = _incident_pool()

    first = recheck_targets(pool)
    for hypothesis in first:
        review_recheck.mark_recheck_issued(hypothesis)
    second = recheck_targets(pool)

    assert len(first) == 3
    assert second == []


def test_the_gates_this_one_does_not_own_are_left_alone() -> None:
    """Safety, evidence, duplicate and failed-review blocks decide elsewhere."""
    foreign = ["unsafe", "evidence_blocked", "review_failed", "duplicate"]
    pool = []
    for disposition in foreign:
        hypothesis = _blocked(0)
        hypothesis.review_disposition = disposition
        pool.append(hypothesis)

    assert recheck_targets(pool) == []


def test_an_idea_the_cascade_already_rejected_is_not_rechecked() -> None:
    """A fatal mature verdict short-circuits, so a recheck cannot clear it."""
    hypothesis = _blocked(0)
    hypothesis.enrichments["full"] = {"verdict": "rejected"}

    assert recheck_targets([hypothesis]) == []
