"""Report section rendering the run's synthesized Knowledge Base.

Split out of ``report_markdown`` to keep that module within the size cap.
``report_content._knowledge_base_topics`` / ``_synthesized_knowledge_base_
topics`` already build this list -- assembled into the report payload by
``report_build.py`` and rendered in the React UI -- but the markdown export
never emitted it (R12-6).

Google's published Knowledge Base wraps a "Knowledge Summary" of named
subject headings, each holding dense encyclopedic prose, and carries **zero
citations anywhere in the span** -- unlike every other numbered report
section, which cites inline throughout. So unlike the claim-evidence and
research-overview renderers, this one deliberately never touches a topic's
``reference_ids``: adding a citation apparatus here would be a local
invention, not a mirror.
"""

from __future__ import annotations

from typing import Any


def _render_topic(topic: dict[str, Any]) -> list[str]:
    """Render one topic as a named subject heading with its prose."""
    title = str(topic.get("title") or "").strip()
    if not title:
        return []
    lines = [f"#### {title}\n"]
    for key in ("summary", "detail", "uncertainty"):
        text = str(topic.get(key) or "").strip()
        if text:
            lines.append(f"{text}\n")
    return lines


def _render_knowledge_base_markdown(topics: list[dict[str, Any]]) -> list[str]:
    """Render the 'Knowledge Base' section, or nothing when no topics exist."""
    lines: list[str] = []
    for topic in topics:
        if isinstance(topic, dict):
            lines += _render_topic(topic)
    if not lines:
        return []
    return ["\n## Knowledge Base\n", "### Knowledge Summary\n", *lines]
