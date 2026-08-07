"""Formatting helpers shared by several prompt-builder modules."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from co_scientist.constants import truncate


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


def _format_connection(connection: Any) -> str:
    """Format one potential-connection entry as bullet text.

    ``related_hypotheses`` names its subjects by the free-text label the
    meta-review prompt asks for (e.g. "Hypothesis 1"), never full
    hypothesis text, so quoting it back here does not echo pool input.
    """
    if not isinstance(connection, dict):
        return str(connection)
    opportunity = str(connection.get("synthesis_opportunity") or "").strip()
    kind = str(connection.get("connection_type") or "").strip()
    if opportunity and kind:
        return f"{kind}: {opportunity}"
    return opportunity or kind or str(connection)


def _covered_areas_section(meta_review: dict[str, Any]) -> str:
    """Render the recurring themes as the areas already explored."""
    return _format_bullet_section(
        "Research Areas Already Covered (Recurring Themes)",
        meta_review.get("emerging_themes", []),
    )


def _open_directions_section(meta_review: dict[str, Any]) -> str:
    """Render the potential connections as directions still open."""
    return _format_bullet_section(
        "Open Directions Flagged for Further Exploration",
        meta_review.get("potential_connections", []),
        _format_connection,
    )


def _meta_review_closing(include_coverage_sections: bool) -> str:
    """Closing instruction, which changes when coverage sections render."""
    closing = "Use these insights to provide more informed and consistent"
    if include_coverage_sections:
        return closing + (
            " reviews, and -- when generating new hypotheses -- to"
            " explore directions distinct from the areas already covered"
            " above.\n"
        )
    return closing + " reviews.\n"


# Reads the state dict shaped by
# agents/meta_review/meta_review.py (which renames the
# schema's strengths/weaknesses fields to common_strengths/
# common_weaknesses when storing state), not the raw META_REVIEW_SCHEMA
# output.
def _format_meta_review_context(
    meta_review: dict[str, Any] | None,
    *,
    include_coverage_sections: bool = True,
) -> str:
    """Format meta-review insights for downstream prompts.

    Spliced into review, ranking, proximity, safety, literature-review, and
    every generation strategy's prompt (I2): the run's own synthesis of
    which areas are already covered and which directions remain open feeds
    back into the next cycle rather than only informing the terminal
    report.

    ``include_coverage_sections`` gates the two "already covered" /
    "open directions" sections specifically (not the strengths/weaknesses/
    recommendations sections, present since before I2). The initial peer-
    review score is the one prompt where this framing is a bad idea to
    default on: its ``novelty`` axis is one of the two the sticky,
    never-revisited review gate consults (``review_gate._DEFAULT_GATE_
    AXES``), and "this area is already covered" reads as a direct novelty
    cue -- which would penalize an Evolution-origin refinement of a
    leading idea for being in the area it was deliberately bred to
    strengthen, at the exact gate a permissive score can never undo (see
    AGENTS.md's "early gate decides the whole run"). ``review.py``'s two
    review-scoring prompt builders (``get_review_prompt``,
    ``get_review_batch_prompt``) pass ``include_coverage_sections=False``;
    every other caller -- generation, ranking (a reversible Elo signal,
    not a gate), proximity (redundancy is exactly what "already covered"
    should flag), literature review, safety, comprehensive reflection, and
    deep verification -- keeps the default.
    """
    if not meta_review or not isinstance(meta_review, dict):
        return ""

    sections = [
        "## Meta-Review Context\n",
        "The following insights were synthesized from previous reviews"
        " of all hypotheses:\n\n",
        _format_bullet_section(
            "Common Strengths Across Hypotheses",
            meta_review.get("common_strengths", []),
        ),
        _format_bullet_section(
            "Common Weaknesses to Watch For",
            meta_review.get("common_weaknesses", []),
        ),
    ]
    if include_coverage_sections:
        sections.append(_covered_areas_section(meta_review))
    sections.append(
        _format_bullet_section(
            "Strategic Recommendations",
            meta_review.get("strategic_recommendations", []),
            _format_recommendation,
        )
    )
    if include_coverage_sections:
        sections.append(_open_directions_section(meta_review))
    sections.append(_meta_review_closing(include_coverage_sections))
    return "".join(sections)


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


def format_lab_constraints_section(
    lab_constraints: list[str] | None,
) -> str:
    """Render the scientist's lab constraints for feasibility prompts (K5).

    Feasibility judgments must reflect the scientist's actual laboratory,
    which the goal interview elicits as explicit constraints. The section
    renders only when constraints exist: an empty list (the scientist
    declared none, or no interview supplied the field) leaves the prompt
    exactly as it was before this section existed.

    Args:
        lab_constraints: Lab constraints elicited during the goal
            interview (equipment, model systems, budget, capabilities).

    Returns:
        The rendered section, or an empty string when there are no
        constraints.
    """
    if not lab_constraints:
        return ""
    items = "\n".join(f"- {constraint}" for constraint in lab_constraints)
    return (
        "## Scientist's Lab Constraints\n\n"
        "The scientist supplied these lab constraints. Respect them when"
        " proposing experiments and judging feasibility: an experiment is"
        " feasible only if it can be run within these constraints, and a"
        " proposal that requires equipment, model systems, or resources"
        " excluded here must say so and offer an alternative that fits.\n\n"
        f"{items}\n"
    )


def _format_bullet_list(
    items: list[str] | None, *, truncate_chars: int | None = None
) -> str:
    """Render items as a "- " bullet list, or "None provided" when empty.

    Args:
        items: Items to render, one per bullet.
        truncate_chars: When given, each item is shortened to this many
            characters via ``constants.truncate`` before being rendered --
            which appends its "..." marker only to items actually cut, so a
            short item renders unmarked. None (the default) renders every
            item in full.
    """
    if not items:
        return "None provided"
    if truncate_chars is not None:
        items = [truncate(item, truncate_chars) for item in items]
    return "\n".join(f"- {item}" for item in items)


def _csv_value(value: Any) -> str:
    """Comma-join a guidance value the model may answer as a list or a scalar.

    The supervisor schema declares these fields as string arrays and the
    prompts render them inline, but production runs on a provider whose
    json_object mode does not enforce the schema, so a bare string arrives
    often enough that all three call sites grew the same isinstance check.

    Args:
        value: A supervisor-guidance field value.

    Returns:
        The list comma-joined, or the value rendered as-is.
    """
    return ", ".join(value) if isinstance(value, list) else str(value)


def _format_csv_list(items: list[str] | None) -> str:
    """Comma-join items, or "None provided" when empty."""
    return ", ".join(items) if items else "None provided"


def _format_authors(authors: list[str]) -> str:
    """Format an author list for paper analysis prompts."""
    return ", ".join(authors) if authors else "Unknown"


def _format_year(year: int | None) -> str:
    """Format a publication year for paper analysis prompts."""
    return str(year) if year else "Unknown"
