"""Per-side review material for the two published ranking prompts.

Published ranking-04 and ranking-05 both hand the judge one review per
hypothesis -- ``Review of hypothesis 1:`` / ``Initial review of hypothesis
1:``. Everything we have already computed about a single hypothesis by
match time is that review: the reviewer's own scores, the Reflection
agent's observation analysis, the deep-verification probes, and the mature
full/simulation/recurrent verdicts. They are composed into one block per
side here so the published input slot points at real content rather than
at nothing, without adding a call: every signal below is read off state
the run already holds.
"""

from dataclasses import dataclass
from typing import Any

_NO_REVIEW = "No review material available for this hypothesis yet."

_NO_REFLECTION = "No reflection notes available."


@dataclass(frozen=True)
class RankingSide:
    """One side of a pairwise tournament match.

    Bundles every per-hypothesis signal the ranking prompt aggregates, so
    the builder takes two symmetric sides instead of eight interleaved
    ``*_a``/``*_b`` parameters.

    Attributes:
        text: The hypothesis text being compared.
        review: This hypothesis's review scores, if it has been reviewed.
        reflection_notes: This hypothesis's reflection notes, if any.
        deep_verification: This hypothesis's deep-verification result
            (``probes`` and ``verdict``), blank before the first pass.
        mature_reviews: This hypothesis's full/simulation/recurrent review
            summary (``mature_review_summary`` shape), blank before the
            mature Reflection cascade has run.
    """

    text: str
    review: dict[str, Any] | None = None
    reflection_notes: str | None = None
    deep_verification: dict[str, Any] | None = None
    mature_reviews: dict[str, dict[str, Any]] | None = None


def _format_review_scores(review: dict[str, Any] | None) -> list[str]:
    """Format one hypothesis's own review scores as bullet lines.

    Args:
        review: The review projection for this side, or None.

    Returns:
        Section lines, or an empty list when the side has no review.
    """
    if not isinstance(review, dict):
        return []

    lines = ["Review scores:\n"]
    for criterion, score in review.get("scores", {}).items():
        lines.append(f"- {criterion}: {score}\n")
    if "overall_score" in review:
        lines.append(f"- Overall Score: {review['overall_score']}\n")
    return lines


def _format_probe_lines(probe: dict[str, Any]) -> list[str]:
    """Format one deep-verification probe's question/answer lines."""
    question = probe.get("question", "")
    answer = probe.get("answer", "")
    fundamental = (
        " (fundamental assumption)"
        if probe.get("assumption_is_fundamental")
        else ""
    )
    lines = [f"- Q{fundamental}: {question}\n"]
    if answer:
        lines.append(f"  A: {answer}\n")
    return lines


def _format_deep_verification_context(
    probes: list[dict[str, Any]] | None, verdict: str | None, label: str
) -> str:
    """Format deep-verification probes for one hypothesis in ranking prompts.

    Returns an empty string when no probes are available so the ranking prompt
    is unchanged on the first tournament (before any deep verification has run).

    Args:
        probes: Probing-question entries from the deep-verification node, or
            None.
        verdict: The deep-verification verdict ("holds", "weakened", or
            "undermined"), or None.
        label: The hypothesis's published number ("1" or "2").

    Returns:
        A formatted block with a leading separator, or an empty string.
    """
    if not probes:
        return ""

    verdict_text = verdict or "unknown"
    sections = [
        f"\nHypothesis {label} Deep Verification (verdict: {verdict_text}):\n"
    ]
    for probe in probes:
        sections.extend(_format_probe_lines(probe))

    return "".join(sections)


_MATURE_REVIEW_SECTION_LABELS: dict[str, str] = {
    "full": "Full review",
    "simulation": "Simulation review",
    "recurrent": "Recurrent review",
}


def _format_mature_review_lines(
    section: str, review: dict[str, Any]
) -> list[str]:
    """Format one full/simulation/recurrent review summary as bullets."""
    lines = [f"- {section} verdict: {review.get('verdict', 'unknown')}\n"]
    justification = review.get("justification")
    if justification:
        lines.append(f"  Justification: {justification}\n")
    for assumption in review.get("assumptions_likely_false") or []:
        lines.append(f"  Assumption likely false: {assumption}\n")
    decisive_step = review.get("decisive_step")
    if decisive_step:
        lines.append(f"  Decisive step: {decisive_step}\n")
    for point in review.get("failure_points") or []:
        lines.append(f"  Failure point: {point}\n")
    return lines


def _format_mature_reviews_context(
    mature_reviews: dict[str, dict[str, Any]] | None, label: str
) -> str:
    """Format mature-review findings for one hypothesis in ranking prompts.

    A fatal finding here -- a full or recurrent review that rejected the
    idea, or a simulation whose mechanism broke down -- must be able to
    influence the verdict (audit E1), so the judge reads each mature
    review's verdict and its decisive findings.

    Returns an empty string when no mature review has run, leaving the
    prompt unchanged before the first mature Reflection cascade.

    Args:
        mature_reviews: The ``mature_review_summary`` projection for this
            hypothesis, or None.
        label: The hypothesis's published number ("1" or "2").

    Returns:
        A formatted block with a leading separator, or an empty string.
    """
    if not mature_reviews:
        return ""

    sections = [f"\nHypothesis {label} Mature Review Findings:\n"]
    for key, section_label in _MATURE_REVIEW_SECTION_LABELS.items():
        review = mature_reviews.get(key)
        if review:
            sections.extend(_format_mature_review_lines(section_label, review))

    return "".join(sections)


def format_side_review(side: RankingSide, label: str) -> str:
    """Compose one side's whole review block for the published slot.

    Args:
        side: The ``RankingSide`` whose review material is being rendered.
        label: The hypothesis's published number ("1" or "2").

    Returns:
        The block that fills ``{{review_1}}``/``{{review_2}}``; never empty,
        so the published input slot always points at something.
    """
    deep_verification = side.deep_verification or {}
    parts = _format_review_scores(side.review)
    parts.append(
        "Reflection Notes (observation analysis):"
        f" {side.reflection_notes or _NO_REFLECTION}\n"
    )
    parts.append(
        _format_deep_verification_context(
            deep_verification.get("probes"),
            deep_verification.get("verdict"),
            label,
        )
    )
    parts.append(_format_mature_reviews_context(side.mature_reviews, label))
    return "".join(parts).strip() or _NO_REVIEW
