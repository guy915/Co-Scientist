"""Formatting helpers shared by several prompt-builder modules."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromptRunContext:
    """Run-scoped context threaded into most node prompts.

    Every field is optional: a builder splices in only the blocks its
    template declares, and an absent value simply renders nothing. Bundling
    them keeps the builders' own parameters about the node's subject matter
    (the goal, the hypotheses, the transcript) rather than the run.

    Attributes:
        supervisor_guidance: The supervisor's plan, formatted per node by
            the caller's `_format_supervisor_guidance_for_*` helper.
        meta_review: Cross-hypothesis meta-review synthesis from the
            previous iteration; blank on iteration 1.
        tool_registry: Tool registry supplying the domain-specific prompt
            customizations; None falls back to the process default.
        run_setup_guidance: Durable run setup guidance text.
        run_focus_guidance: Durable run focus guidance text.
    """

    supervisor_guidance: dict[str, Any] | None = None
    meta_review: dict[str, Any] | None = None
    tool_registry: Any | None = None
    run_setup_guidance: str | None = None
    run_focus_guidance: str | None = None


@dataclass(frozen=True)
class PromptSections:
    """Pre-formatted optional context blocks spliced into a prompt.

    Each field is the already-rendered markdown for one shared template
    placeholder. A None field leaves the placeholder unset, so it renders
    as the `{{MISSING:...}}` sentinel; an empty string sets it to nothing.
    The distinction is deliberate and per-template - see `_build_prompt`.

    Attributes:
        supervisor_guidance: Rendered supervisor-guidance block.
        meta_review_context: Rendered meta-review context block.
        run_guidance: Rendered run setup/focus guidance block.
    """

    supervisor_guidance: str | None = None
    meta_review_context: str | None = None
    run_guidance: str | None = None


def _run_guidance_section(context: PromptRunContext) -> str:
    """Render a run context's setup/focus guidance block."""
    return _format_run_guidance(
        context.run_setup_guidance, context.run_focus_guidance
    )


def _format_bullet_section(
    header: str, items: list[Any], format_item: Callable[[Any], str] = str
) -> str:
    """Render a "**header:**" line followed by one bullet per item.

    Shared by the common-strengths/common-weaknesses/strategic-
    recommendations blocks of `_format_meta_review_context`, which are
    otherwise identical apart from the header text and how each item is
    turned into display text.

    Args:
        header: Bolded sub-header introducing the bullet list (without the
            surrounding `**` or trailing colon).
        items: Items to render as bullets; an empty list renders nothing.
        format_item: Callable turning one item into its bullet text.

    Returns:
        The header and bullet lines followed by a trailing blank line, or
        an empty string when `items` is empty.
    """
    if not items:
        return ""
    lines = [f"**{header}:**\n"]
    lines.extend(f"- {format_item(item)}\n" for item in items)
    lines.append("\n")
    return "".join(lines)


def _format_recommendation(rec: Any) -> str:
    """Format one strategic-recommendation entry as bullet text."""
    if isinstance(rec, dict):
        return str(rec.get("recommendation", str(rec)))
    return str(rec)


# Reads the state dict shaped by nodes/meta_review.py (which renames the
# schema's strengths/weaknesses fields to common_strengths/
# common_weaknesses when storing state), not the raw META_REVIEW_SCHEMA
# output.
def _format_meta_review_context(meta_review: dict[str, Any] | None) -> str:
    """Format meta-review insights for review prompts.

    Used when re-reviewing evolved hypotheses.
    """
    if not meta_review or not isinstance(meta_review, dict):
        return ""

    sections = []
    sections.append("## Meta-Review Context\n")
    sections.append(
        "The following insights were synthesized from previous reviews"
        " of all hypotheses:\n\n"
    )

    sections.append(
        _format_bullet_section(
            "Common Strengths Across Hypotheses",
            meta_review.get("common_strengths", []),
        )
    )
    sections.append(
        _format_bullet_section(
            "Common Weaknesses to Watch For",
            meta_review.get("common_weaknesses", []),
        )
    )
    sections.append(
        _format_bullet_section(
            "Strategic Recommendations",
            meta_review.get("strategic_recommendations", []),
            _format_recommendation,
        )
    )

    sections.append(
        "Use these insights to provide more informed and consistent reviews.\n"
    )

    return "".join(sections) if sections else ""


def _format_run_guidance(
    run_setup_guidance: str | None = None, run_focus_guidance: str | None = None
) -> str:
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


def _format_bullet_list(items: list[str] | None) -> str:
    """Render items as a "- " bullet list, or "None provided" when empty."""
    if not items:
        return "None provided"
    return "\n".join(f"- {item}" for item in items)


def _format_csv_list(items: list[str] | None) -> str:
    """Comma-join items, or "None provided" when empty."""
    return ", ".join(items) if items else "None provided"


def _format_authors(authors: list[str]) -> str:
    """Format an author list for paper analysis prompts."""
    return ", ".join(authors) if authors else "Unknown"


def _format_year(year: int | None) -> str:
    """Format a publication year for paper analysis prompts."""
    return str(year) if year else "Unknown"
