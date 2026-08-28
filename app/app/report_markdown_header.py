"""Report header rendering: title, the run's configuration, and provenance.

Split out of ``report_markdown`` to keep that module within the size cap.
Renders, in the published order (MASH report L3-40 then L41): the title and
provider line, "Research Goal Details" -- goal, requirements, attributes,
criteria, all collected by ``run_modes.setup_config`` into the run's
persisted ``setup`` block but never rendered before (R12-8) -- then a
provenance and caution line naming this system and when the report was
prepared (R12-20), then the optional summary paragraph.
"""

from __future__ import annotations

import datetime
from typing import Any

# Kept close to Google's published wording ("Prepared by AI co-scientist on
# 2026-06-12. For research purposes only.") but naming this system, not
# Google's -- claiming to be Google's product would misattribute the report.
_SYSTEM_NAME = "Co-Scientist"


def _render_setup_list(label: str, items: Any) -> list[str]:
    """Render a 'Label:' bullet list, or nothing when there is no content."""
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


def _render_provenance_line(prepared_at: float | None) -> list[str]:
    """Render the provenance and research-purposes-only caution line.

    Absent when the caller has no timestamp for this report (a demo or a
    report persisted before this field existed) -- a caution line naming
    a date this system does not actually know would misstate provenance,
    not just omit it.
    """
    if prepared_at is None:
        return []
    date = datetime.datetime.fromtimestamp(
        prepared_at, tz=datetime.timezone.utc
    ).date()
    return [
        f"_Prepared by {_SYSTEM_NAME} on {date.isoformat()}."
        " For research purposes only._",
        "",
    ]


def _render_report_header(
    research_goal: str,
    provider: str,
    summary: str | None,
    setup: dict[str, Any] | None = None,
    prepared_at: float | None = None,
) -> list[str]:
    """Render the title, provider line, goal details, provenance, and summary.

    Sections render only when their data is present.
    """
    lines = [
        f"# Research Report — {research_goal}",
        "",
        f"_Provider: **{provider}**_",
        "",
    ]
    lines += _render_research_goal_details(research_goal, setup)
    lines += _render_provenance_line(prepared_at)
    if summary:
        lines += ["## Summary", summary, ""]
    return lines
