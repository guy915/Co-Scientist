"""Research-overview markdown renderers for the report.

Renders the engine's ``research_overview`` payload — the overview summary
and research directions, the NIH Specific Aims section, and the research
contacts — as markdown lines. Split from ``report_markdown`` by concern;
every function here is pure and ``report_markdown`` re-exports each name so
its namespace keeps resolving.
"""

from __future__ import annotations

from typing import Any


def _render_optional_paragraph(text: str | None) -> list[str]:
    """Render a single trailing-blank-line paragraph, or nothing when empty."""
    return [f"{text}\n"] if text else []


def _render_experiments_list(experiments: list[Any]) -> list[str]:
    """Render the 'Suggested experiments' bullet list, or nothing when empty."""
    if not experiments:
        return []
    return (
        ["Suggested experiments:\n"]
        + [f"- {experiment}" for experiment in experiments]
        + [""]
    )


def _render_research_direction(direction: dict[str, Any]) -> list[str]:
    """Render one research-direction entry, or nothing when not a dict."""
    if not isinstance(direction, dict):
        return []
    lines = [f"### {direction.get('title', '')}\n"]
    lines += _render_optional_paragraph(direction.get("importance", ""))
    lines += _render_experiments_list(
        direction.get("suggested_experiments") or []
    )
    return lines


def _has_overview_content(summary: str | None, directions: list[Any]) -> bool:
    """Return whether the overview section has any renderable content."""
    return bool(summary or directions)


def _render_directions_list(directions: list[Any]) -> list[str]:
    """Render each research-direction entry in sequence."""
    lines: list[str] = []
    for direction in directions:
        lines += _render_research_direction(direction)
    return lines


def _render_overview_section(ov: dict[str, Any]) -> list[str]:
    """Render the 'Research Overview' section, or nothing when data absent."""
    if not isinstance(ov, dict):
        return []
    summary = ov.get("summary")
    directions = ov.get("research_directions") or []
    if not _has_overview_content(summary, directions):
        return []
    lines = ["\n## Research Overview\n"]
    lines += _render_optional_paragraph(summary)
    return lines + _render_directions_list(directions)


def _render_nih_aim(aim: dict[str, Any]) -> list[str]:
    """Render one NIH aim entry, or nothing when not a dict."""
    if not isinstance(aim, dict):
        return []
    lines = [f"### {aim.get('aim', '')}\n"]
    rationale = aim.get("rationale", "")
    if rationale:
        lines.append(f"**Rationale:** {rationale}\n")
    approach = aim.get("approach", "")
    if approach:
        lines.append(f"**Approach:** {approach}\n")
    return lines


def _has_aims_content(
    introduction: str | None, aims: list[Any], impact: str | None
) -> bool:
    """Return whether the NIH aims section has any renderable content."""
    return bool(introduction or aims or impact)


def _render_aims_list(aims: list[Any]) -> list[str]:
    """Render each NIH aim entry in sequence."""
    lines: list[str] = []
    for aim in aims:
        lines += _render_nih_aim(aim)
    return lines


def _render_impact(impact: str | None) -> list[str]:
    """Render the 'Impact' subsection, or nothing when absent."""
    return ["### Impact\n", f"{impact}\n"] if impact else []


def _render_nih_aims_section(aims_section: dict[str, Any]) -> list[str]:
    """Render the 'NIH Specific Aims' section, or nothing when data absent."""
    if not isinstance(aims_section, dict):
        return []
    introduction = aims_section.get("introduction")
    aims = aims_section.get("aims") or []
    impact = aims_section.get("impact")
    if not _has_aims_content(introduction, aims, impact):
        return []
    lines = ["\n## NIH Specific Aims\n"]
    lines += _render_optional_paragraph(introduction)
    lines += _render_aims_list(aims)
    lines += _render_impact(impact)
    return lines


def render_research_overview_markdown(overview: dict[str, Any]) -> list[str]:
    """Render the research overview + NIH Specific Aims as markdown lines.

    Args:
        overview: The engine ``research_overview`` payload, shaped as
            ``{"overview": {...}, "nih_specific_aims": {...}}``. May be empty
            or carry empty sub-dicts for runs without hypotheses.

    Returns:
        A list of markdown lines. Empty when no renderable content exists, so
        callers never emit bare section headers.
    """
    # The isinstance guard here (and inside each section renderer) is
    # defensive: this payload can originate from LLM-produced structured
    # output (engine path), which is schema-validated but still worth
    # guarding defensively against a malformed or missing sub-shape rather
    # than raising here.
    if not isinstance(overview, dict):
        return []
    lines = _render_overview_section(overview.get("overview") or {})
    lines += _render_nih_aims_section(overview.get("nih_specific_aims") or {})
    lines += _render_research_contacts_section(
        overview.get("research_contacts") or []
    )
    return lines


def _render_contact_evidence_line(contact: dict[str, Any]) -> list[str]:
    """Render a contact's source-evidence line, or nothing when unsourced."""
    title, url = contact.get("source_title"), contact.get("source_url")
    if not title:
        return []
    return [f"Evidence: [{title}]({url})\n" if url else f"Evidence: {title}\n"]


def _render_contact_entry(contact: dict[str, Any]) -> list[str]:
    """Render one research-contact entry, or nothing when unnamed."""
    if not isinstance(contact, dict) or not contact.get("name"):
        return []
    lines = [f"### {contact['name']}\n"]
    if contact.get("expertise"):
        lines.append(f"**Relevant expertise:** {contact['expertise']}\n")
    if contact.get("justification"):
        lines.append(f"{contact['justification']}\n")
    lines += _render_contact_evidence_line(contact)
    return lines


def _render_research_contacts_section(contacts: Any) -> list[str]:
    """Render the 'Research Contacts' section, or nothing when empty."""
    if not isinstance(contacts, list) or not contacts:
        return []
    lines = ["\n## Research Contacts\n"]
    for contact in contacts:
        lines += _render_contact_entry(contact)
    return lines
