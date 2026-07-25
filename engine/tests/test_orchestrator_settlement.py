"""Settlement-allowance lifecycle and the owed-coverage termination bound.

Covers the orchestrator-side half of owed-coverage settlement: deriving the
unmatched count from the pool, and initialising, decrementing, and never
refilling the allowance that bounds how long the scheduler may override a
budget ceiling to finish owed tournament rounds.
"""

from co_scientist.agents.supervisor.orchestrator import _rankable_coverage
from co_scientist.models import Hypothesis


def _hyp(hyp_id: str, wins: int = 0, losses: int = 0) -> Hypothesis:
    """A minimal rankable hypothesis with the given match tally."""
    return Hypothesis(
        id=hyp_id,
        text=f"statement {hyp_id}",
        win_count=wins,
        loss_count=losses,
    )


def test_rankable_coverage_counts_never_matched_hypotheses() -> None:
    # A healthy average hides individual zeros: two ideas at two matches
    # each averages 1.33 across three, passing a 1.0 average gate while one
    # idea has never played.
    rankable, avg, unmatched = _rankable_coverage(
        [_hyp("a", wins=2), _hyp("b", losses=2), _hyp("c")]
    )

    assert rankable == 3
    assert avg > 1.0
    assert unmatched == 1


def test_rankable_coverage_ignores_unrankable_hypotheses() -> None:
    # An evidence-gate-rejected idea can never accrue matches, so counting
    # it as unmatched would demand tournament rounds that cannot help it.
    blocked = _hyp("blocked")
    blocked.review_disposition = "evidence_blocked"

    rankable, _, unmatched = _rankable_coverage([_hyp("a", wins=1), blocked])

    assert rankable == 1
    assert unmatched == 0
