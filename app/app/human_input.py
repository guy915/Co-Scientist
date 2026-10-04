from __future__ import annotations

import dataclasses

from co_scientist.constants import NEEDS_REVISION_SCORE, NOT_VIABLE_SCORE

from app.hypothesis.safety import (
    HypothesisSafetyReview,
    escalate_review,
    review_hypothesis_safety,
)
from app.text_utils import first_sentence

# Keep the scientist origin sentinel aligned with the engine so generation and
# human authorship stay distinct.
SCIENTIST_MANUAL_ORIGIN = "scientist_manual"


@dataclasses.dataclass(frozen=True)
class HumanHypothesisAdmission:
    admitted: bool
    safety_review: HypothesisSafetyReview
    author: str
    hypothesis: dict[str, object] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "admitted": self.admitted,
            "author": self.author,
            "safety": self.safety_review.to_dict(),
            "hypothesis": self.hypothesis,
        }


def _build_admitted_hypothesis(
    text: str, author: str, title: str, review: HypothesisSafetyReview
) -> dict[str, object]:
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


def _admission_from_review(
    text: str, author: str, title: str, review: HypothesisSafetyReview
) -> HumanHypothesisAdmission:
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


def admit_human_hypothesis(
    *,
    text: str,
    author: str,
    title: str = "",
) -> HumanHypothesisAdmission:
    """Scientist authorship never bypasses generated hypotheses' safety,
    review, proximity or tournament-entry requirements.
    """
    review = review_hypothesis_safety(text)
    return _admission_from_review(text, author, title, review)


async def admit_human_hypothesis_with_escalation(
    *,
    text: str,
    author: str,
    run_id: str,
    title: str = "",
    db_path: str | None = None,
) -> HumanHypothesisAdmission:
    """Resolve eligible Tier B uncertainty through the same contextual
    policy; provider work runs outside any SQLite transaction.
    """
    review = await escalate_review(
        review_hypothesis_safety(text), text, run_id=run_id, db_path=db_path
    )
    return _admission_from_review(text, author, title, review)


@dataclasses.dataclass(frozen=True)
class HumanReview:
    hypothesis_id: str
    author: str
    verdict: str  # "support" | "oppose" | "revise"
    critique: str

    def to_dict(self) -> dict[str, str]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "reviewer_agent": "scientist",
            "author": self.author,
            "verdict": self.verdict,
            "critique": self.critique,
        }


# Human categorical verdicts share agents' 1-10 rubric because the latest review
# score enters ranking/evolution prompts.
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
