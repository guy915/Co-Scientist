"""Render research directions, questions, Specific Aims and research contacts.

Model-written fields may contain objects, lists or serialized JSON; text
coercion and contact grouping live beside the sections that use them.
"""

from __future__ import annotations

import json
from typing import Any


def _readable_text(value: Any) -> str:
    """Flatten a possibly-malformed field into readable plain text.

    Flattens a JSON-looking string, a dict, or a list into human-readable
    text, and passes a well-formed string through unchanged.
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


def _render_contact_evidence_line(contact: dict[str, Any]) -> list[str]:
    """Render a contact's source-evidence line, or nothing when unsourced."""
    title = _readable_text(contact.get("source_title"))
    url = contact.get("source_url")
    if not title:
        return []
    source = f"[{title}]({url})" if url else title
    return [f"**Supporting article:** {source}\n"]


def _render_contact_entry(
    contact: dict[str, Any],
    *,
    heading: str = "###",
    show_direction: bool = True,
) -> list[str]:
    """Render one research-contact entry, or nothing when unnamed.

    ``heading``/``show_direction`` let a grouped rendering nest a
    contact one level under its group's own direction heading without
    repeating the direction line that heading already states; the
    defaults reproduce MO-7's original flat shape unchanged, which every
    ungrouped contact still uses.
    """
    if not isinstance(contact, dict) or not contact.get("name"):
        return []
    lines = [f"{heading} {_readable_text(contact['name'])}\n"]
    if show_direction:
        direction = _readable_text(contact.get("research_direction"))
        if direction:
            lines.append(f"**Research direction:** {direction}\n")
    lines += _render_contact_body(contact)
    lines += _render_contact_evidence_line(contact)
    return lines


def _render_contact_body(contact: dict[str, Any]) -> list[str]:
    """Render a contact's expertise and justification lines, or nothing."""
    lines: list[str] = []
    expertise = _readable_text(contact.get("expertise"))
    if expertise:
        lines.append(f"**Relevant expertise:** {expertise}\n")
    justification = _readable_text(contact.get("justification"))
    if justification:
        lines.append(f"**Justification:** {justification}\n")
    return lines


def _direction_key(direction: Any) -> str:
    """Normalize a research-direction tag for group/contact matching."""
    return _readable_text(direction).casefold()


def _render_group_example_titles(
    example_hypothesis_ids: Any, hypothesis_title_by_id: dict[str, str]
) -> list[str]:
    """Render a group's 'Example Hypothesis Titles' bullets, or nothing."""
    ids = (
        example_hypothesis_ids
        if isinstance(example_hypothesis_ids, list)
        else []
    )
    titles = [
        hypothesis_title_by_id[hid]
        for hid in ids
        if isinstance(hid, str) and hypothesis_title_by_id.get(hid)
    ]
    if not titles:
        return []
    return (
        ["**Example Hypothesis Titles:**\n"]
        + [f"- {title}" for title in titles]
        + [""]
    )


def _render_contact_group(
    group: dict[str, Any],
    contacts: list[dict[str, Any]],
    hypothesis_title_by_id: dict[str, str],
) -> list[str]:
    """Render one direction group: heading, rationale, examples, contacts.

    Nothing renders when the group names no direction, or no contact in
    this report actually matched it (a group the model wrote for a
    direction that has no corresponding contact tag) -- a heading with
    nothing under it is worse than omitting it.
    """
    direction = _readable_text(group.get("research_direction"))
    if not direction or not contacts:
        return []
    lines = [f"### {direction}\n"]
    rationale = _readable_text(group.get("rationale"))
    if rationale:
        lines.append(f"**Why they are best for this direction:** {rationale}\n")
    lines += _render_group_example_titles(
        group.get("example_hypothesis_ids"), hypothesis_title_by_id
    )
    for contact in contacts:
        lines += _render_contact_entry(
            contact, heading="####", show_direction=False
        )
    return lines


def _partition_contacts_by_group(
    contacts: list[Any], group_keys: set[str]
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Split contacts into per-group buckets and an ungrouped remainder."""
    by_key: dict[str, list[dict[str, Any]]] = {key: [] for key in group_keys}
    ungrouped: list[dict[str, Any]] = []
    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        key = _direction_key(contact.get("research_direction"))
        if key and key in by_key:
            by_key[key].append(contact)
        else:
            ungrouped.append(contact)
    return by_key, ungrouped


def _render_grouped_contacts(
    contacts: list[Any],
    groups: Any,
    hypothesis_title_by_id: dict[str, str],
) -> list[str]:
    """Render every contact, grouped by direction where a group matches.

    A contact whose direction matches no group renders exactly as MO-7's
    flat shape always has, so this is purely additive: an old report, or
    a response that never populates ``research_contact_groups``, looks
    unchanged.
    """
    valid_groups = [g for g in (groups or []) if isinstance(g, dict)]
    group_keys = {
        _direction_key(g.get("research_direction")) for g in valid_groups
    }
    by_key, ungrouped = _partition_contacts_by_group(contacts, group_keys)

    lines: list[str] = []
    for group in valid_groups:
        key = _direction_key(group.get("research_direction"))
        lines += _render_contact_group(
            group, by_key.get(key, []), hypothesis_title_by_id
        )
    for contact in ungrouped:
        lines += _render_contact_entry(contact)
    return lines


def _render_research_contacts_section(
    contacts: Any,
    groups: Any = None,
    hypothesis_title_by_id: dict[str, str] | None = None,
) -> list[str]:
    """Render the 'Research Contacts' section, or nothing when empty."""
    if not isinstance(contacts, list) or not contacts:
        return []
    lines = ["\n## Research Contacts\n"]
    lines += _render_grouped_contacts(
        contacts, groups, hypothesis_title_by_id or {}
    )
    return lines


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
    # F7: the exemplar's own "Example idea:" block, printed between the
    # topic's reasoning and its questions exactly where cf-PICI prints it.
    # Absent on a report persisted before the field existed, which renders
    # as it always did.
    example_idea = _readable_text(sub_topic.get("example_idea", ""))
    if example_idea:
        lines.append(f"**Example idea:** {example_idea}\n")
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


def _direction_titles(directions: list[Any]) -> list[str]:
    """Collect each direction's title, dropping malformed/untitled entries."""
    titles = []
    for direction in directions:
        if not isinstance(direction, dict):
            continue
        title = _readable_text(direction.get("title", ""))
        if title:
            titles.append(title)
    return titles


def _render_directions_preview(directions: list[Any]) -> list[str]:
    """Render a compact preview list naming each direction, or nothing."""
    titles = _direction_titles(directions)
    if len(titles) < 2:
        return []
    return (
        ["We will be focusing on these research directions:\n"]
        + [f"- {title}" for title in titles]
        + [""]
    )


def _render_unexpected_direction(direction: Any) -> str:
    """Render one unexpected-research-direction bullet, or "" when unnamed.

    Task B: a bolded name plus prose, matching MASH's own published
    ``Unexpected Research Directions`` bullets. Degrades a missing
    description to a bare title bullet, the same contract
    ``_render_evaluation_criterion`` (report/markdown/process.py)
    follows for a missing criterion description.
    """
    if not isinstance(direction, dict):
        return ""
    title = _readable_text(direction.get("title", ""))
    if not title:
        return ""
    description = _readable_text(direction.get("description", ""))
    return f"- **{title}:** {description}" if description else f"- {title}"


def _render_unexpected_directions_section(directions: list[Any]) -> list[str]:
    """Render 'Unexpected research directions', or [] when nothing usable."""
    lines = [
        line
        for direction in directions
        if (line := _render_unexpected_direction(direction))
    ]
    if not lines:
        return []
    return ["\n### Unexpected research directions\n", *lines]


def _render_overview_section(
    ov: dict[str, Any], unexpected_directions: list[Any]
) -> list[str]:
    """Render the 'Research Overview' section, or nothing when data absent."""
    if not isinstance(ov, dict):
        return []
    summary = _readable_text(ov.get("summary"))
    directions = ov.get("research_directions") or []
    unexpected_lines = _render_unexpected_directions_section(
        unexpected_directions
    )
    if not _has_overview_content(summary, directions) and not unexpected_lines:
        return []
    lines = ["\n## Research Overview\n"]
    lines += _render_optional_paragraph(summary)
    lines += _render_directions_preview(directions)
    lines += _render_directions_list(directions)
    lines += unexpected_lines
    return lines


def _render_pattern_list(heading: str, items: Any) -> list[str]:
    """Render a heading and its bullet items, or nothing when empty.

    Local to this module rather than importing
    ``report.markdown.meta_review._render_bullet_list``: that module
    already imports from this one (``_render_optional_paragraph``), and
    importing back would be circular.
    """
    values = _readable_text_list(items)
    if not values:
        return []
    return [f"\n{heading}\n"] + [f"- {v}" for v in values]


def _render_open_questions_section(payload: dict[str, Any]) -> list[str]:
    """Render 'Open questions' plus its Clear/Unexpected patterns pair."""
    questions = _readable_text_list(payload.get("open_questions") or [])
    clear_lines = _render_pattern_list(
        "### Clear patterns", payload.get("clear_patterns") or []
    )
    unexpected_lines = _render_pattern_list(
        "### Unexpected patterns", payload.get("unexpected_patterns") or []
    )
    if not (questions or clear_lines or unexpected_lines):
        return []
    lines = ["\n## Open questions\n"]
    if questions:
        lines += [f"{i}. {q}" for i, q in enumerate(questions, 1)]
        lines.append("")
    lines += clear_lines
    lines += unexpected_lines
    return lines


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
#
# F4: all three published aims pages head each aim "Specific Aims N" and
# print the goal as a labelled block beneath it ("Overarching goal:" /
# "Hypothesis:" / "Reasoning:"). We used to put the goal text *in* the
# heading, which dropped the label the exemplars print. The legacy "aim"
# spelling joins the body for the same reason: reports stored before the
# exemplar vocabulary carry it instead of overarching_goal, and it must
# not vanish now that the heading is a fixed number.
_AIM_BODY_FIELDS = (
    ("overarching_goal", "Overarching goal"),
    ("aim", "Aim"),
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


def _render_nih_aim(aim: dict[str, Any], number: int) -> list[str]:
    """Render one numbered NIH aim entry, or nothing when not a dict."""
    if not isinstance(aim, dict):
        return []
    lines = [f"### Specific Aims {number}\n"]
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
    for number, aim in enumerate(aims, 1):
        lines += _render_nih_aim(aim, number)
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


def research_overview_sections(
    overview: dict[str, Any],
    hypothesis_title_by_id: dict[str, str] | None = None,
) -> list[list[str]]:
    """Return the overview's four optional sub-sections, each its own list."""
    # The isinstance guard here (and inside each section renderer) is
    # defensive: this payload can originate from LLM-produced structured
    # output (engine path), which is schema-validated but still worth
    # guarding defensively against a malformed or missing sub-shape rather
    # than raising here.
    if not isinstance(overview, dict):
        return [[], [], [], []]
    return [
        _render_overview_section(
            overview.get("overview") or {},
            overview.get("unexpected_research_directions") or [],
        ),
        _render_open_questions_section(overview),
        _render_nih_aims_section(overview.get("nih_specific_aims") or {}),
        _render_research_contacts_section(
            overview.get("research_contacts") or [],
            overview.get("research_contact_groups"),
            hypothesis_title_by_id,
        ),
    ]


def render_research_overview_markdown(
    overview: dict[str, Any],
    hypothesis_title_by_id: dict[str, str] | None = None,
) -> list[str]:
    """Render the research overview + NIH Specific Aims as markdown lines.

    Returns:
        A list of markdown lines. Empty when no renderable content exists, so
        callers never emit bare section headers.
    """
    lines: list[str] = []
    for section in research_overview_sections(overview, hypothesis_title_by_id):
        lines += section
    return lines
