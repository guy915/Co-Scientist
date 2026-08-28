"""Report header rendering: title and the run's configuration.

Split out of ``report_markdown`` to keep that module within the size cap.
Renders the title and provider line, then "Research Goal Details" -- goal,
requirements, attributes, criteria, all collected by
``run_modes.setup_config`` into the run's persisted ``setup`` block but
never rendered before (R12-8) -- matching the published order (MASH report
opens with this block, L3-40, before any hypothesis content).
"""

from __future__ import annotations

from typing import Any


def _render_setup_list(label: str, items: Any) -> list[str]:
    """Render a 'Label:' bullet list, or nothing when there is nothing to say."""
    values = [str(item) for item in items or [] if str(item).strip()]
    if not values:
        return []
    return [f"**{label}:**\n"] + [f"- {value}" for value in values] + [""]


def _render_research_goal_details(
    research_goal: str, setup: dict[str, Any] | None
) -> list[str]:
    """Render 'Research Goal Details': goal, requirements, attributes, criteria.

    Nothing renders when the run carries no setup block (a report persisted
    before this field existed) or an empty one.
    """
    if not isinstance(setup, dict):
        return []
    fields = [
        _render_setup_list(label, setup.get(key))
        for label, key in (
            ("Requirements", "requirements"),
            ("Attributes", "attributes"),
            ("Criteria", "criteria"),
        )
    ]
    if not any(fields):
        return []
    lines = ["## Research Goal Details\n", f"**Goal:** {research_goal}\n"]
    for field_lines in fields:
        lines += field_lines
    return lines


def _render_report_header(
    research_goal: str,
    provider: str,
    summary: str | None,
    setup: dict[str, Any] | None = None,
) -> list[str]:
    """Render the title, provider line, goal details, and optional summary."""
    lines = [
        f"# Research Report — {research_goal}",
        "",
        f"_Provider: **{provider}**_",
        "",
    ]
    lines += _render_research_goal_details(research_goal, setup)
    if summary:
        lines += ["## Summary", summary, ""]
    return lines
