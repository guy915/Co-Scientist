"""Research-overview markdown renderers for the report.

Renders the engine's ``research_overview`` payload — the overview summary
and research directions, the NIH Specific Aims section, and the research
contacts — as markdown lines. Split from ``report_markdown`` by concern;
every function here is pure and ``report_markdown`` re-exports each name so
its namespace keeps resolving.
"""

from __future__ import annotations

import json
from typing import Any


def _readable_text(value: Any) -> str:
    """Flatten a possibly-malformed field into readable plain text.

    Research-overview fields come from the model in json_object mode with no
    server-side schema enforcement, so a field the schema declares a string
    can arrive as a dict, or as a string that is itself serialized JSON.
    Emitting that verbatim leaks raw JSON into the report. This flattens a
    JSON-looking string, a dict, or a list into human-readable text, and
    passes a well-formed string through unchanged.
    """
    if isinstance(value, str):
        return _readable_from_string(value)
    if isinstance(value, list):
        return _join_readable(value, " ")
    if isinstance(value, dict):
        return _join_readable(list(value.values()), " - ")
    return "" if value is None else str(value)


def _readable_from_string(value: str) -> str:
    """Parse and flatten a JSON-looking string; else return it unchanged."""
    trimmed = value.strip()
    if not _is_json_like(trimmed):
        return value
    try:
        return _readable_text(json.loads(trimmed))
    except (ValueError, TypeError):
        return value


def _is_json_like(text: str) -> bool:
    """Whether the string looks like a serialized JSON object or array."""
    return (text.startswith("{") and text.endswith("}")) or (
        text.startswith("[") and text.endswith("]")
    )


def _join_readable(values: list[Any], separator: str) -> str:
    """Flatten each value to text, drop the empties, and join them."""
    return separator.join(
        text for text in (_readable_text(item) for item in values) if text
    )


def _readable_text_list(value: Any) -> list[str]:
    """Flatten a possibly-malformed list field into readable strings.

    Tolerates a JSON-encoded string, a lone dict, or a list whose items are
    dicts or serialized JSON, mirroring ``_readable_text``.
    """
    if isinstance(value, str):
        return _list_from_string(value)
    if isinstance(value, list):
        return [text for text in map(_readable_text, value) if text]
    if isinstance(value, dict):
        text = _readable_text(value)
        return [text] if text else []
    return []


def _list_from_string(value: str) -> list[str]:
    """Parse a JSON-array string into readable items; else a single line."""
    trimmed = value.strip()
    if not trimmed:
        return []
    if not _is_json_like(trimmed):
        return [trimmed]
    try:
        return _readable_text_list(json.loads(trimmed))
    except (ValueError, TypeError):
        return [trimmed]


def _render_optional_paragraph(text: str | None) -> list[str]:
    """Render a single trailing-blank-line paragraph, or nothing when empty."""
    return [f"{text}\n"] if text else []


def _render_experiments_list(experiments: list[Any]) -> list[str]:
    """Render the 'Suggested experiments' bullet list, or nothing when empty."""
    items = _readable_text_list(experiments)
    if not items:
        return []
    return (
        ["Suggested experiments:\n"]
        + [f"- {experiment}" for experiment in items]
        + [""]
    )


def _render_specific_questions(questions: list[Any]) -> list[str]:
    """Render a sub-topic's 'Specific questions' list, or nothing when empty."""
    items = _readable_text_list(questions)
    if not items:
        return []
    return (
        ["Specific questions:\n"]
        + [f"- {question}" for question in items]
        + [""]
    )


def _render_sub_topic(sub_topic: dict[str, Any]) -> list[str]:
    """Render one named sub-topic entry, or nothing when not a dict.

    MO-1: both published exemplars nest a named sub-topic one level below
    the direction ("Areas of Research" / "What to Research in This
    Area?"), each carrying its own why, what, and specific questions.
    """
    if not isinstance(sub_topic, dict):
        return []
    title = _readable_text(sub_topic.get("title", ""))
    lines = [f"#### {title}\n"] if title else []
    why = _readable_text(sub_topic.get("why", ""))
    if why:
        lines.append(f"**Why:** {why}\n")
    what = _readable_text(sub_topic.get("what", ""))
    if what:
        lines.append(f"**What:** {what}\n")
    lines += _render_specific_questions(
        sub_topic.get("specific_questions") or []
    )
    return lines


def _render_sub_topics_list(sub_topics: list[Any]) -> list[str]:
    """Render each sub-topic entry in sequence."""
    lines: list[str] = []
    for sub_topic in sub_topics:
        lines += _render_sub_topic(sub_topic)
    return lines


def _render_research_direction(direction: dict[str, Any]) -> list[str]:
    """Render one research-direction entry, or nothing when not a dict."""
    if not isinstance(direction, dict):
        return []
    lines = [f"### {_readable_text(direction.get('title', ''))}\n"]
    lines += _render_optional_paragraph(
        _readable_text(direction.get("importance", ""))
    )
    # MO-12: the "what is already known" slot ALS's exemplar names
    # "Recent Findings" (cf-PICI folds the same idea into a bullet under
    # "Why Research This Area?" instead of naming it separately).
    recent_findings = _readable_text(direction.get("recent_findings", ""))
    if recent_findings:
        lines.append(f"**Recent findings:** {recent_findings}\n")
    lines += _render_experiments_list(
        direction.get("suggested_experiments") or []
    )
    lines += _render_sub_topics_list(direction.get("sub_topics") or [])
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
    summary = _readable_text(ov.get("summary"))
    directions = ov.get("research_directions") or []
    if not _has_overview_content(summary, directions):
        return []
    lines = ["\n## Research Overview\n"]
    lines += _render_optional_paragraph(summary)
    return lines + _render_directions_list(directions)


# The page's blocks, in the order Google's published Specific Aims
# exemplars print them (paper A.5.3): three preamble sections, the aims,
# then the pilot study. Reports written before the engine adopted that
# vocabulary carry an "introduction"/"impact" pair instead and are still
# stored, so both spellings render -- an old report must not lose its aims
# page because the schema moved on.
_AIMS_PREAMBLE_BLOCKS = (
    ("disease_description", "Disease Description"),
    ("unmet_need", "Unmet Need"),
    ("proposed_solution", "Proposed Solution"),
)
_AIMS_CLOSING_BLOCKS = (
    ("pilot_evaluation", "Pilot Evaluation"),
    ("impact", "Impact"),
)
# Per-aim fields, new spelling first: the exemplars give every aim a goal,
# the hypothesis it tests, and the reasoning behind it. Only one spelling
# is ever present, so the whole list renders in order.
_AIM_BODY_FIELDS = (
    ("hypothesis", "Hypothesis"),
    ("reasoning", "Reasoning"),
    ("rationale", "Rationale"),
    ("approach", "Approach"),
)


def _render_labeled_blocks(
    section: dict[str, Any], blocks: tuple[tuple[str, str], ...]
) -> list[str]:
    """Render each present block as its own headed subsection."""
    lines: list[str] = []
    for key, heading in blocks:
        text = _readable_text(section.get(key))
        if text:
            lines += [f"### {heading}\n", f"{text}\n"]
    return lines


def _render_nih_aim(aim: dict[str, Any]) -> list[str]:
    """Render one NIH aim entry, or nothing when not a dict."""
    if not isinstance(aim, dict):
        return []
    heading = _readable_text(aim.get("overarching_goal", "")) or _readable_text(
        aim.get("aim", "")
    )
    lines = [f"### {heading}\n"]
    for key, label in _AIM_BODY_FIELDS:
        text = _readable_text(aim.get(key, ""))
        if text:
            lines.append(f"**{label}:** {text}\n")
    return lines


def _has_aims_content(
    preamble: list[str], aims: list[Any], closing: list[str]
) -> bool:
    """Return whether the NIH aims section has any renderable content."""
    return bool(preamble or aims or closing)


def _render_aims_list(aims: list[Any]) -> list[str]:
    """Render each NIH aim entry in sequence."""
    lines: list[str] = []
    for aim in aims:
        lines += _render_nih_aim(aim)
    return lines


def _render_nih_aims_section(aims_section: dict[str, Any]) -> list[str]:
    """Render the 'NIH Specific Aims' section, or nothing when data absent."""
    if not isinstance(aims_section, dict):
        return []
    preamble = _render_optional_paragraph(
        _readable_text(aims_section.get("introduction"))
    ) + _render_labeled_blocks(aims_section, _AIMS_PREAMBLE_BLOCKS)
    aims = aims_section.get("aims") or []
    closing = _render_labeled_blocks(aims_section, _AIMS_CLOSING_BLOCKS)
    if not _has_aims_content(preamble, aims, closing):
        return []
    return [
        "\n## NIH Specific Aims\n",
        *preamble,
        *_render_aims_list(aims),
        *closing,
    ]


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
    title = _readable_text(contact.get("source_title"))
    url = contact.get("source_url")
    if not title:
        return []
    return [f"Evidence: [{title}]({url})\n" if url else f"Evidence: {title}\n"]


def _render_contact_entry(contact: dict[str, Any]) -> list[str]:
    """Render one research-contact entry, or nothing when unnamed."""
    if not isinstance(contact, dict) or not contact.get("name"):
        return []
    lines = [f"### {_readable_text(contact['name'])}\n"]
    # MO-7: ties the contact back to the direction that surfaced them,
    # matching the published exemplar's "Research Direction: X" tag.
    # Absent on a report persisted before this field existed.
    direction = _readable_text(contact.get("research_direction"))
    if direction:
        lines.append(f"**Research direction:** {direction}\n")
    expertise = _readable_text(contact.get("expertise"))
    if expertise:
        lines.append(f"**Relevant expertise:** {expertise}\n")
    justification = _readable_text(contact.get("justification"))
    if justification:
        lines.append(f"{justification}\n")
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
