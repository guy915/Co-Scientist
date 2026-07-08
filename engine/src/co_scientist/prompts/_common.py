"""Formatting helpers shared by several prompt-builder modules."""
# pylint: disable=inconsistent-quotes

from typing import Any


# Reads the state dict shaped by nodes/meta_review.py (which renames the
# schema's strengths/weaknesses fields to common_strengths/
# common_weaknesses when storing state), not the raw META_REVIEW_SCHEMA
# output.
def _format_meta_review_context(meta_review: dict[str, Any] | None) -> str:
    """Format meta-review insights for review prompts (when re-reviewing evolved
    hypotheses).
    """
    if not meta_review or not isinstance(meta_review, dict):
        return ""

    sections = []
    sections.append("## Meta-Review Context\n")
    sections.append(
        "The following insights were synthesized from previous reviews"
        " of all hypotheses:\n\n")

    common_strengths = meta_review.get("common_strengths", [])
    if common_strengths:
        sections.append("**Common Strengths Across Hypotheses:**\n")
        for strength in common_strengths:
            sections.append(f"- {strength}\n")
        sections.append("\n")

    common_weaknesses = meta_review.get("common_weaknesses", [])
    if common_weaknesses:
        sections.append("**Common Weaknesses to Watch For:**\n")
        for weakness in common_weaknesses:
            sections.append(f"- {weakness}\n")
        sections.append("\n")

    strategic_recommendations = meta_review.get("strategic_recommendations", [])
    if strategic_recommendations:
        sections.append("**Strategic Recommendations:**\n")
        for rec in strategic_recommendations:
            if isinstance(rec, dict):
                rec_text = rec.get("recommendation", str(rec))
            else:
                rec_text = str(rec)
            sections.append(f"- {rec_text}\n")
        sections.append("\n")

    sections.append(
        "Use these insights to provide more informed and consistent reviews.\n")

    return "".join(sections) if sections else ""


def _format_run_guidance(run_setup_guidance: str | None = None,
                         run_focus_guidance: str | None = None) -> str:
    """Format durable run setup/focus guidance for downstream prompts."""
    sections = []
    if run_setup_guidance:
        sections.append("## Run Setup Guidance\n")
        sections.append(run_setup_guidance.strip())
        sections.append("\n")
    if run_focus_guidance:
        sections.append("## Run Focus Guidance\n")
        sections.append(run_focus_guidance.strip())
        sections.append("\n")
    return "\n".join(sections).strip()


def _format_authors(authors: list[str]) -> str:
    """Format an author list for paper analysis prompts."""
    return ", ".join(authors) if authors else "Unknown"


def _format_year(year: int | None) -> str:
    """Format a publication year for paper analysis prompts."""
    return str(year) if year else "Unknown"
