"""One forced review pass for a hypothesis the budget would drop unreviewed.

``_check_review_backlog`` (``scheduling.policy_checks``) already forces a
REFLECT whenever ``unreviewed_count > 0``, but it sits below
``_budget_termination``. A hypothesis admitted -- by generation,
evolution, or a scientist's own contribution -- on the same cycle that
also exhausts the run's budget therefore has no peer review at all, and
the next decision terminates on that same exhausted budget before review
ever runs: it reaches the final pool and the report unreviewed
(``docs/PARITY.md``, HITL-MANUAL-HYP-001).

This module decides which unreviewed ideas get that one overriding pass
(``scheduling.policy_checks._check_owed_review``). It selects them; it
does not review them itself -- the actual call still goes through the
ordinary review path (``review.review_node`` / the durable review
fan-out), so the verdict and every downstream consumer are unchanged.

**Bounded the same way ``review_recheck`` bounds a blocked idea's one
recheck, and for the same reason:** a hypothesis whose review keeps
failing is exactly the population that would otherwise re-arm a bare
"unreviewed" trigger forever. Once per hypothesis for the whole run,
marked on a checkpointed enrichment *before* the review's outcome is
known -- so a failed attempt still spends it -- plus a run-wide ceiling
on top, identical in shape to ``review_recheck.MAX_RECHECKS_PER_RUN``.
"""

from collections.abc import Iterable

from co_scientist.models import Hypothesis, has_peer_review

# Enrichment key recording that this hypothesis has already had its one
# budget-overriding review attempt issued. Rides in ``enrichments``, which
# is checkpointed with the hypothesis -- the same shape as
# ``review_recheck.RECHECK_MARKER`` / ``verification.
# VERIFICATION_MARKER`` -- so a resumed run does not re-open an override
# that already fired.
OWED_REVIEW_MARKER = "owed_review_issued"

# Run-wide ceiling, over and above the per-hypothesis rule -- mirrors
# ``review_recheck.MAX_RECHECKS_PER_RUN``. Bounds the worst case even
# against a pool that keeps growing with newly-admitted, never-reviewed
# ideas: however many are ever owed the override across the whole run, no
# more than this many ever spend one.
MAX_OWED_REVIEW_OVERRIDES_PER_RUN = 24

# Foreign disposition this override must leave alone. Proximity's archive
# marker (the app's ``drain.hypotheses.DEDUPLICATED_REVIEW_DISPOSITION``,
# spelled out here because the engine may not import the app -- mirrors
# ``review_gate._FOREIGN_DISPOSITIONS``' own "duplicate" entry) can land on
# an idea before it is ever peer-reviewed, since the app archives a
# duplicate rather than pruning it from the pool the way the streaming
# engine's proximity node does. Reviewing an idea the report already
# excludes buys nothing, so ``not has_peer_review`` alone is not a
# sufficient test here.
_ARCHIVED_DISPOSITION = "duplicate"


def owed_review_issued(hypothesis: Hypothesis) -> bool:
    """Return whether this hypothesis already had its one override."""
    return bool(hypothesis.enrichments.get(OWED_REVIEW_MARKER))


def mark_owed_review_issued(hypothesis: Hypothesis) -> None:
    """Record the override attempt, before its answer is known.

    Marked on issue rather than on success: a failed review has still
    spent the attempt, and re-firing on failure is exactly how a bounded
    override becomes a per-cycle one for the hypothesis the reviewer keeps
    failing on.
    """
    hypothesis.enrichments[OWED_REVIEW_MARKER] = True


def _is_owed(hypothesis: Hypothesis) -> bool:
    """Return whether one never-issued hypothesis is owed the override."""
    if hypothesis.review_disposition == _ARCHIVED_DISPOSITION:
        return False
    return not has_peer_review(hypothesis)


def owed_review_targets(hypotheses: Iterable[Hypothesis]) -> list[Hypothesis]:
    """Return the unreviewed hypotheses still owed the override, within budget.

    Args:
        hypotheses: The run's whole hypothesis pool.

    Returns:
        The hypotheses the override may fire for now, capped so the run's
        issued overrides never exceed ``MAX_OWED_REVIEW_OVERRIDES_PER_RUN``.
    """
    issued = 0
    pending: list[Hypothesis] = []
    for hypothesis in hypotheses:
        if owed_review_issued(hypothesis):
            issued += 1
        elif _is_owed(hypothesis):
            pending.append(hypothesis)
    return pending[: max(MAX_OWED_REVIEW_OVERRIDES_PER_RUN - issued, 0)]


def owed_review_count(hypotheses: Iterable[Hypothesis]) -> int:
    """Return how many hypotheses are currently owed the override.

    The count the scheduling policy reads
    (``SchedulerStats.owed_review_count``): zero once every unreviewed idea
    has either been reviewed or already spent its one override, whichever
    came first.
    """
    return len(owed_review_targets(hypotheses))
