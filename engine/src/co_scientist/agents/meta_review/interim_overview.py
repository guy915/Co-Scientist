"""The interim research overview, written for and read by generation (FIX-6).

The paper describes the research overview as generated *periodically* and
names it as one of two channels by which the system improves on itself --
the other being meta-review's critique, which already loops back into the
generation prompts. Ours ran once, at termination, so the second channel
was write-only: nothing the synthesis concluded could reach the ideas still
being drafted.

A non-terminal firing writes the block below instead of publishing an
overview (``research_overview`` stays the finished document's own key), and
generation splices it into the context its strategies already read. Kept
compact on purpose: it lands in every generation prompt of the next cycle,
so it carries the directions and the open questions -- what the run should
push on next -- and not the aims page, the contacts or the knowledge base,
which are written for a reader rather than for a drafting model.
"""

from __future__ import annotations

from typing import Any, Final

from co_scientist.state import WorkflowState

_MAX_DIRECTIONS: Final = 4
"""Directions carried into the next cycle's prompts."""

_MAX_QUESTIONS: Final = 5
"""Open questions carried into the next cycle's prompts."""

_HEADER: Final = (
    "## Interim research overview (this run's own synthesis so far)\n\n"
    "The system synthesized the ideas produced so far into the directions"
    " and open questions below. Push into what they leave open: prefer a"
    " mechanism, model system or intervention these do not already cover,"
    " and do not re-derive a direction already named here.\n"
)


def build_interim_overview(response: dict[str, Any]) -> str:
    """Render a drafted overview response as the block generation reads.

    Args:
        response: The raw research-overview synthesis response.

    Returns:
        The formatted block, or an empty string when the response carries
        neither a direction nor an open question.
    """
    overview = response.get("overview")
    directions = (
        overview.get("research_directions")
        if isinstance(overview, dict)
        else None
    )
    lines = _titled_lines(directions, "Directions", _MAX_DIRECTIONS)
    lines += _question_lines(response.get("open_questions"))
    return f"{_HEADER}\n" + "\n".join(lines) + "\n" if lines else ""


def _titled_lines(raw: Any, header: str, limit: int) -> list[str]:
    """Render up to ``limit`` titled entries as one bulleted block."""
    if not isinstance(raw, list):
        return []
    bullets = [
        f"- {str(item.get('title') or '').strip()}"
        for item in raw[:limit]
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    ]
    return [f"**{header}:**", *bullets, ""] if bullets else []


def _question_lines(raw: Any) -> list[str]:
    """Render up to ``_MAX_QUESTIONS`` open questions as a bulleted block."""
    if not isinstance(raw, list):
        return []
    bullets = [
        f"- {str(item).strip()}"
        for item in raw[:_MAX_QUESTIONS]
        if str(item).strip()
    ]
    return ["**Open questions:**", *bullets, ""] if bullets else []


def format_interim_overview(state: WorkflowState) -> str:
    """Return the interim overview block, or "" before the first firing.

    Args:
        state: The workflow state the generate node was entered with.

    Returns:
        The block written by the most recent periodic firing, or an empty
        string when this run has not had one.
    """
    return str(state.get("interim_overview") or "").strip()
