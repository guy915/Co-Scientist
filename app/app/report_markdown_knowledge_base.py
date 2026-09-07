"""Report section rendering the run's synthesized Knowledge Base.

Split out of ``report_markdown`` to keep that module within the size cap.
``report_content._knowledge_base_topics`` / ``_synthesized_knowledge_base_
topics`` already build this list -- assembled into the report payload by
``report_build.py`` and rendered in the React UI -- but the markdown export
never emitted it (R12-6).

Google's published Knowledge Base is a two-level hierarchy of *headings*:
a top-level "Knowledge Summary" wrapping named themes, each theme wrapping
the named subject headings that hold the prose. Our depths map onto it as
``## Knowledge Base`` (the exemplar's "Knowledge Summary"), ``### <theme>``
and ``#### <subject>``. "Knowledge Summary" survives here only as the label
for the *flat* fallback shape, which has no themes to name -- so a report
whose Knowledge Base carries a single ``### Knowledge Summary`` is reading
the degraded path, not a one-theme synthesis (production run d1273490
rendered 8 themes over 38 sections as bold paragraphs under that label, and
looked degraded in every heading-based view).

The span carries **zero citations anywhere** -- unlike every other numbered
report section, which cites inline throughout. So unlike the claim-evidence
and research-overview renderers, this one deliberately never touches a
topic's ``reference_ids``: adding a citation apparatus here would be a
local invention, not a mirror.
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


_FLAT_LABEL = "Knowledge Summary"
"""Heading for topics carrying no theme -- the flat fallback shape.

Deliberately not reused for a themed section: it is the one visible mark
distinguishing the degraded path (the research-overview call's own capped
flat topics) from a funded deep synthesis.
"""


def _render_knowledge_base_markdown(topics: list[dict[str, Any]]) -> list[str]:
    """Render the 'Knowledge Base' section, or nothing when no topics exist.

    Topics carrying a ``theme`` (the deep synthesis, F8) are grouped under
    it as a real ``###`` heading, one level above the ``####`` subject
    headings that belong to it, mirroring the exemplar's own hierarchy. A
    topic with no theme -- the flat shape the research-overview call still
    produces -- falls under ``### Knowledge Summary``, byte-identical to
    what a run that did not fund the deep pass rendered before.
    """
    lines: list[str] = []
    label = ""
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        rendered = _render_topic(topic)
        if not rendered:
            continue
        label, heading = _theme_heading(topic, label)
        lines += heading + rendered
    if not lines:
        return []
    return ["\n## Knowledge Base\n", *lines]


def _theme_heading(
    topic: dict[str, Any], current: str
) -> tuple[str, list[str]]:
    """Return the heading label in force and the line it needs, if any."""
    label = str(topic.get("theme") or "").strip() or _FLAT_LABEL
    if label == current:
        return label, []
    return label, [f"### {label}\n"]
