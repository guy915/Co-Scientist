"""The hypothesis-review record and its serialization helpers.

Split out of :mod:`co_scientist.models`, which had grown past the
module-size budget. ``HypothesisReview`` and the serialization helpers that
project a ``Hypothesis`` into its claim/assessment payload fragments have no
tie to the tournament/lineage mechanics that dominate that file, so they
separate cleanly; ``Hypothesis`` itself is only referenced here as a type
hint (``TYPE_CHECKING``-guarded), so there is no import cycle back to
:mod:`co_scientist.models`.

:mod:`co_scientist.models` re-exports every name here, so every existing
import site is unaffected.
"""

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from co_scientist.models import Hypothesis


@dataclass
class HypothesisReview:
    """Review of a hypothesis with scores and feedback.

    already_explored/novel_aspects are the published novelty review's two
    named lists (MO-3): what the hypothesis overlaps with existing work
    known to the reviewer, and what it does not. Distinct from the
    "novelty" entry in scores/detailed_feedback, which is a 1-10 rating
    rather than an enumeration.
    """

    review_summary: str
    scores: dict[str, int]  # scientific_soundness, novelty, relevance, etc.
    safety_ethical_concerns: str
    detailed_feedback: dict[str, str]
    constructive_feedback: str
    overall_score: float
    already_explored: list[str] = field(default_factory=list)
    novel_aspects: list[str] = field(default_factory=list)


def _rebuild_reviews(
    reviews_data: list[dict[str, Any]],
) -> list[HypothesisReview]:
    """Rebuild serialized review dicts into HypothesisReview instances."""
    return [HypothesisReview(**review) for review in reviews_data]


def _reviews_to_dicts(
    reviews: list[HypothesisReview],
) -> list[dict[str, Any]]:
    """Serialize HypothesisReview instances into plain dicts.

    ``asdict`` rather than a hand-written field list: the inverse
    ``_rebuild_reviews`` splats straight back into the dataclass, so a field
    added to ``HypothesisReview`` and not to the list here would round-trip
    as a silently missing key.
    """
    return [dataclasses.asdict(r) for r in reviews]


def _claim_fields(hypothesis: "Hypothesis") -> dict[str, Any]:
    """Serialize what the hypothesis asserts, as generation wrote it.

    Args:
        hypothesis: The hypothesis being serialized.

    Returns:
        The claim, its supporting prose, and the citations it rests on.
    """
    return {
        # Also referred to as "hypothesis" in other contexts.
        "text": hypothesis.text,
        "category": hypothesis.category,
        "introduction": hypothesis.introduction,
        "recent_findings": hypothesis.recent_findings,
        "explanation": hypothesis.explanation,
        "literature_grounding": hypothesis.literature_grounding,
        "experiment": hypothesis.experiment,
        # "literature_review_used": hypothesis.literature_review_used,
        "novelty_validation": hypothesis.novelty_validation,
        "enrichments": hypothesis.enrichments,
        "citation_map": hypothesis.citation_map,
    }


def _assessment_fields(hypothesis: "Hypothesis") -> dict[str, Any]:
    """Serialize what the run's review agents concluded about a hypothesis.

    Args:
        hypothesis: The hypothesis being serialized.

    Returns:
        The reviews, proximity/evolution traces, deep-verification result,
        and the review and safety dispositions gating publication.
    """
    return {
        "reviews": _reviews_to_dicts(hypothesis.reviews),
        "similarity_cluster_id": hypothesis.similarity_cluster_id,
        "evolution_history": hypothesis.evolution_history,
        "reflection_notes": hypothesis.reflection_notes,
        "deep_verification_probes": hypothesis.deep_verification_probes,
        "deep_verification_verdict": hypothesis.deep_verification_verdict,
        "deep_verification_fingerprint": (
            hypothesis.deep_verification_fingerprint
        ),
        "review_disposition": hypothesis.review_disposition,
        "safety_status": hypothesis.safety_status,
    }


# Review dispositions that keep a hypothesis out of the Elo tournament: the
# initial peer-review gate (inaccurate / non-novel / unsafe) and the
# pre-ranking evidence gate (evidence_blocked). Shared by ranking and the
# scheduler so tournament-coverage accounting matches tournament eligibility.
#
# "unsafe" is the reviewer's own safety axis reaching the not-viable band
# (finding J8). It is kept apart from the two quality dispositions because
# the reader is owed the actual reason: an idea withheld for a safety
# concern is not an inaccurate one.
#
# Note what is deliberately absent: "needs_revision" and "duplicate". A
# weak-but-not-fatal idea still competes and publishes -- the tournament,
# not a single early review, decides its standing (see
# agents/reflection/review.py::_apply_initial_review_gate). A duplicate is
# archived by proximity rather than judged, so it is excluded through its
# own path and reported as a duplicate, not as a failed idea.
#
# Also deliberately absent, and for a third reason: the deep-verification
# verdict "undermined". It is not a disposition at all, and it no longer
# withholds an idea -- see Hypothesis.is_rankable / is_undermined.
BLOCKING_REVIEW_DISPOSITIONS = frozenset(
    {
        "inaccurate",
        "non_novel",
        "inaccurate_and_non_novel",
        "unsafe",
        "evidence_blocked",
    }
)

# The deep-verification verdict for a hypothesis whose fundamental
# assumption failed a probe. Demoting, not blocking: the idea ranks last
# among the sound ones and publishes carrying the verdict. Defined here
# rather than in the verification node because the ordering, the persisted
# state, and the node all have to agree on the exact string.
UNDERMINED_VERDICT = "undermined"
