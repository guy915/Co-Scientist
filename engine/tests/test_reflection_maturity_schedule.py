"""Which mature reviews a hypothesis is still owed.

The full and simulation reviews are both due at first maturity and both
fail independently, so "which are done" is two facts. Reading it as one
-- maturity inferred from the full review alone -- re-issued a
simulation review that had already succeeded, once per iteration, for as
long as the full review kept failing.
"""

from __future__ import annotations

from co_scientist.agents.reflection.mature_reviews import (
    reviews_needed,
)
from tests._state import make_hypothesis


def _modes(hypothesis: object, iteration: int) -> list[str]:
    """The review modes due, as the strings the schedulers key on."""
    return [review.value for review in reviews_needed(hypothesis, iteration)]  # type: ignore[arg-type]


class TestFirstMaturity:
    def test_a_fresh_hypothesis_is_owed_both(self) -> None:
        assert _modes(make_hypothesis(text="a"), 0) == ["full", "simulation"]

    def test_a_succeeded_simulation_is_not_re_issued(self) -> None:
        """The defect: a review that passed, re-run because another failed.

        Harmless while both were one LLM call. Not harmless once the
        simulation review runs a tool loop it pays for per firing -- and
        the cost recurred every iteration, because nothing about a
        failing full review stops the next iteration asking again.
        """
        hypothesis = make_hypothesis(text="a")
        hypothesis.enrichments["simulation"] = {"verdict": "breaks_down"}

        for iteration in (0, 1, 2):
            assert _modes(hypothesis, iteration) == ["full"]

    def test_a_succeeded_full_moves_the_hypothesis_on(self) -> None:
        # Maturity still turns on the full review; only the redundant
        # re-issue is gone.
        hypothesis = make_hypothesis(text="a")
        hypothesis.enrichments["full"] = {"verdict": "sound"}

        assert _modes(hypothesis, 1) == ["recurrent"]


class TestOnceMature:
    def test_a_recurrent_review_is_owed_once_per_iteration(self) -> None:
        hypothesis = make_hypothesis(text="a")
        hypothesis.enrichments["full"] = {"verdict": "sound"}
        hypothesis.enrichments["recurrent_review_iteration"] = 2

        assert _modes(hypothesis, 2) == []
        assert _modes(hypothesis, 3) == ["recurrent"]


class TestWhatIsDeliberatelyNotRetried:
    """A failed simulation review is not re-issued once the run matures."""

    def test_a_failed_simulation_is_not_retried_after_full_succeeds(
        self,
    ) -> None:
        """Recorded as a decision, because it is one and it is arguable.

        Maturity turns on the full review, so a hypothesis whose full
        review succeeded moves to recurrent reviews carrying whatever
        simulation result it got -- including none. Retrying the
        simulation later would mean a fresh tool loop, on the tiers where
        that is the expensive part, to fill in a review the hypothesis
        has already been assessed without. The complete review set is
        worth less than the cost of completing it, so the gap stands.

        If that trade is ever revisited, this test is the thing to
        change; today it stops the behaviour being re-derived by
        accident in either direction.
        """
        hypothesis = make_hypothesis(text="a")
        hypothesis.enrichments["full"] = {"verdict": "sound"}

        for iteration in (0, 1, 2):
            assert "simulation" not in _modes(hypothesis, iteration)
            hypothesis.enrichments["recurrent_review_iteration"] = iteration
