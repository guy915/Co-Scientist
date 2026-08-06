"""Scientist-in-the-loop hypotheses and reviews (Milestone 7).

Scientists can contribute their own hypotheses and reviews, which the paper
ranks alongside (and combines with) system-generated ones (SSR §5). The
invariant is that a human-added hypothesis uses the *same* safety,
review, proximity, and tournament-entry path as a generated one, and retains
authorship provenance.

This module is the admission boundary: it runs the per-hypothesis safety review
(the same `hypothesis_safety.review_hypothesis_safety` every generated
hypothesis passes) and, when admitted, stamps `origin="scientist_manual"` and
the author so the tournament and reports can attribute it. It does not itself
persist or rank — it produces the admitted hypothesis payload the normal
pipeline consumes, so there is exactly one safety/entry path.
"""

from __future__ import annotations

import dataclasses

from co_scientist.constants import NEEDS_REVISION_SCORE, NOT_VIABLE_SCORE

from app.hypothesis_safety import (
    HypothesisSafetyReview,
    review_hypothesis_safety,
)
from app.text_utils import first_sentence

# Origin marker matching the engine's HypothesisOrigin.SCIENTIST_MANUAL, so a
# human hypothesis is attributed distinctly from generation/evolution.
SCIENTIST_MANUAL_ORIGIN = "scientist_manual"


@dataclasses.dataclass(frozen=True)
class HumanHypothesisAdmission:
    """The outcome of admitting a scientist-authored hypothesis."""

    admitted: bool
    safety_review: HypothesisSafetyReview
    author: str
    hypothesis: dict[str, object] | None

    def to_dict(self) -> dict[str, object]:
        """Serialize the admission decision for an audit/event record."""
        return {
            "admitted": self.admitted,
            "author": self.author,
            "safety": self.safety_review.to_dict(),
            "hypothesis": self.hypothesis,
        }


def _build_admitted_hypothesis(
    text: str, author: str, title: str, review: HypothesisSafetyReview
) -> dict[str, object]:
    """Build the admitted hypothesis payload stamped with human provenance."""
    return {
        "title": title or first_sentence(text),
        "statement": text,
        "origin": SCIENTIST_MANUAL_ORIGIN,
        "created_by_agent": SCIENTIST_MANUAL_ORIGIN,
        "author": author,
        "generation": 0,
        "parent_id": None,
        "safety_outcome": review.outcome.value,
    }


def admit_human_hypothesis(
    *,
    text: str,
    author: str,
    title: str = "",
) -> HumanHypothesisAdmission:
    """Admit a scientist-authored hypothesis through the shared safety path.

    Runs the same per-hypothesis safety review generated hypotheses pass. If
    the review blocks (prohibited/ethical/uncertain), the hypothesis is not
    admitted (no bypass for human authorship). Otherwise it returns an admitted
    hypothesis payload stamped with `origin="scientist_manual"` and the author,
    ready to enter the normal review/proximity/tournament path.

    Args:
        text: The scientist's hypothesis statement.
        author: Opaque author identifier (for authorship provenance).
        title: Optional short title; derived from the text when omitted.

    Returns:
        The :class:`HumanHypothesisAdmission`.
    """
    review = review_hypothesis_safety(text)
    if review.blocks_tournament:
        return HumanHypothesisAdmission(
            admitted=False,
            safety_review=review,
            author=author,
            hypothesis=None,
        )
    hypothesis = _build_admitted_hypothesis(text, author, title, review)
    return HumanHypothesisAdmission(
        admitted=True,
        safety_review=review,
        author=author,
        hypothesis=hypothesis,
    )


@dataclasses.dataclass(frozen=True)
class HumanReview:
    """A scientist-contributed review of a hypothesis, with authorship."""

    hypothesis_id: str
    author: str
    verdict: str  # "support" | "oppose" | "revise"
    critique: str

    def to_dict(self) -> dict[str, str]:
        """Serialize for the reviews audit record."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "reviewer_agent": "scientist",
            "author": self.author,
            "verdict": self.verdict,
            "critique": self.critique,
        }


# A scientist verdict is categorical, but the engine hands every review to
# the tournament as a number: `Hypothesis.review_summary()` projects the
# *latest* review's `overall_score` into the ranking and evolution prompts.
# A merged human review is that latest review, so its score is read side by
# side with the agents' -- and those come from the 1-10 rubric the review
# prompts hand the model (co_scientist.constants documents the bands). The
# earlier 20/60/90 was off that scale entirely, so a supported idea arrived
# at the judge claiming a score no agent review could reach, and an opposed
# one still outscored every agent review. These map each verdict onto the
# band of the same rubric that means it: "not viable" for oppose, "needs
# substantial rework" for revise, and the good-to-outstanding band for
# support.
_SUPPORTED_SCORE = 8

VERDICT_REVIEW_SCORES: dict[str, int] = {
    "support": _SUPPORTED_SCORE,
    "revise": NEEDS_REVISION_SCORE,
    "oppose": NOT_VIABLE_SCORE,
}

_VALID_VERDICTS = frozenset(VERDICT_REVIEW_SCORES)


def build_human_review(
    *, hypothesis_id: str, author: str, verdict: str, critique: str
) -> HumanReview:
    """Validate and build a scientist review for the shared reviews path.

    The verdict must be one of support/oppose/revise so a human review enters
    the same reviews table as an agent review, attributed to its author.

    Raises:
        ValueError: If the verdict is not a recognized value.
    """
    normalized = verdict.strip().lower()
    if normalized not in _VALID_VERDICTS:
        raise ValueError(
            f"verdict must be one of {sorted(_VALID_VERDICTS)}, got {verdict!r}"
        )
    return HumanReview(
        hypothesis_id=hypothesis_id,
        author=author,
        verdict=normalized,
        critique=critique,
    )
