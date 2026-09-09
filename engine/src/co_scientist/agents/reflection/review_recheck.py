"""One recurrent review per blocked idea, once per run.

Deriving ``review_disposition`` from the whole review record instead of
writing it once (``review_gate.derive_review_disposition``) only helps if
a *later* verdict can arrive. For a blocked idea none can: the mature
cascade selects on ``review_disposition == "viable"``
(``comprehensive_reflection``, ``research_evidence``), so a blocked idea
is never re-examined, produces no deeper verdict, and the run that
blocked 20 of 22 ideas would block 20 of 22 again.

This module decides which blocked ideas get one more look. It selects
them; it does not judge them -- the review it triggers is stored through
``mature_reviews.store_mature_review_result`` like every other mature
review, so the disposition still comes from the one derived path.

**Bounded twice, because blocked ideas are exactly the population that
grows when the gate misfires.** Once per hypothesis for the whole run
(the marker below), and a hard run-wide ceiling on top. The cost is
therefore ``+blocked_count`` calls *once* -- about +20 on the incident
run, ~1.6% of the express tier's 1200-call ceiling -- never a per-cycle
multiplier. Re-reviewing every blocked idea every cycle was considered
and rejected (audit FIX-4, variant (c)).

The review type is the recurrent one for the same reason: it reuses the
full-review schema and verdicts, so ``mature_disposition`` reads it
unchanged, but ``review_evidence._review_evidence_for`` gives it no
retrieval -- so a recheck is exactly one provider call, where a full
review is two (query formulation) plus retrieval.

Known edge, recorded rather than fixed: ``mature_disposition`` walks the
cascade in ``full -> simulation -> recurrent`` order and the last
non-fatal verdict wins, which assumes recurrent postdates full. A recheck
inverts that for one hypothesis, so an idea a recheck cleared whose
*later* full review says ``needs_revision`` reads ``viable`` until its
next genuine recurrent review overwrites the stored result. The
consequence is one iteration of cascade-filter membership, which is not
worth a precedence change in the shared write path.
"""

from collections.abc import Iterable

from co_scientist.agents.reflection.mature_reviews import mature_disposition
from co_scientist.agents.reflection.review_gate import scientist_disposition
from co_scientist.agents.reflection.review_types import ReviewType
from co_scientist.models import Hypothesis

# The review issued as a recheck. Not a free choice: it has to be one the
# cascade's own disposition table already reads (``mature_reviews``).
RECHECK_REVIEW_TYPE = ReviewType.RECURRENT

# Enrichment key recording that this hypothesis has had its one recheck.
# It rides in ``enrichments``, which is checkpointed with the hypothesis,
# so a run that resumes from SQLite does not re-fire the whole wave --
# a marker held only in memory turns a bounded cost into an unbounded one
# on every restart.
RECHECK_MARKER = "review_recheck_issued"

# The run-wide ceiling, over and above the per-hypothesis rule. Sized to
# cover the 22-idea incident run whole while bounding the largest pool
# this system has actually produced (46 ideas) to roughly 2% of the
# express tier's call budget.
MAX_RECHECKS_PER_RUN = 24

# The blocks this recheck owns: the review gate's own not-viable band
# (``review_gate._fatal_disposition``). Every other blocking value is
# decided elsewhere and must not be re-opened here -- ``unsafe`` is the
# reviewer's safety axis, which a correctness review is never asked
# about; ``evidence_blocked`` belongs to the app's pre-ranking evidence
# gate, which restores the disposition it displaced itself;
# ``review_failed`` records a call that produced no review to revisit;
# ``duplicate`` is proximity's archive marker. Stated as an allow-list so
# a new disposition elsewhere cannot silently become recheckable.
_RECHECKABLE_DISPOSITIONS: frozenset[str] = frozenset(
    {"inaccurate", "non_novel", "inaccurate_and_non_novel"}
)


def recheck_issued(hypothesis: Hypothesis) -> bool:
    """Return whether this hypothesis has already had its one recheck."""
    return bool(hypothesis.enrichments.get(RECHECK_MARKER))


def mark_recheck_issued(hypothesis: Hypothesis) -> None:
    """Record the recheck attempt, before its answer is known.

    Marked on issue rather than on success: a failed call has still spent
    the attempt, and re-firing on failure is how a bounded wave becomes a
    per-cycle one for exactly the ideas the reviewer keeps failing on.
    """
    hypothesis.enrichments[RECHECK_MARKER] = True


def _is_recheckable(hypothesis: Hypothesis) -> bool:
    """Return whether one blocked idea is this recheck's to re-open.

    The cascade having no opinion yet (``mature_disposition`` is None) is
    part of the test, not a shortcut: a hypothesis the cascade itself
    rejected carries the same ``inaccurate`` disposition, and its fatal
    verdict short-circuits, so a recurrent ``sound`` could never clear it.
    """
    if hypothesis.review_disposition not in _RECHECKABLE_DISPOSITIONS:
        return False
    # A block a scientist asked for is not the gate misfiring, so there is
    # nothing here to re-open: the derivation restores the verdict
    # whatever a recurrent review answers, and the call is spent for
    # nothing (see ``review_gate.derive_review_disposition``).
    if scientist_disposition(hypothesis) == "inaccurate":
        return False
    return mature_disposition(hypothesis) is None


def recheck_targets(hypotheses: Iterable[Hypothesis]) -> list[Hypothesis]:
    """Return the blocked ideas due one recurrent review, within budget.

    Both bounds are read off the pool rather than tracked in a counter, so
    they hold across a checkpoint round trip and a run resume without a
    state channel of their own.

    Args:
        hypotheses: The run's whole hypothesis pool.

    Returns:
        The hypotheses to recheck now, capped so the run's issued
        rechecks never exceed ``MAX_RECHECKS_PER_RUN``.
    """
    issued = 0
    pending: list[Hypothesis] = []
    for hypothesis in hypotheses:
        if recheck_issued(hypothesis):
            issued += 1
        elif _is_recheckable(hypothesis):
            pending.append(hypothesis)
    return pending[: max(MAX_RECHECKS_PER_RUN - issued, 0)]
