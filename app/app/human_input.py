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


_VALID_VERDICTS = frozenset({"support", "oppose", "revise"})


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
