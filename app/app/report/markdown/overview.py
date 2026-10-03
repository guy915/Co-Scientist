"""Research overview and meta-review sections for the Goal Report."""

from __future__ import annotations

import json
from typing import Any, NamedTuple


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


def _render_points(points: Any) -> list[str]:
    """Render a critique point's guidance sub-points as indented bullets."""
    if not isinstance(points, list):
        return []
    return [f"  - {point}" for point in points if str(point).strip()]


def _sub_theme_headline(name: str, description: str) -> str:
    """Render a critique point's own bullet line.

    Named and described is the published shape ("Primary Driver vs.
    Consequence: A very common critique ..."); either alone still gets a
    bullet rather than an empty label.
    """
    if name and description:
        return f"- **{name}**: {description}"
    return f"- {name or description}"


def _render_sub_theme(sub_theme: Any) -> list[str]:
    """Render one critique point and its guidance sub-points."""
    if not isinstance(sub_theme, dict):
        text = str(sub_theme).strip()
        return [f"- {text}"] if text else []
    name = str(sub_theme.get("theme") or "").strip()
    description = str(sub_theme.get("description") or "").strip()
    if not name and not description:
        return []
    return [
        _sub_theme_headline(name, description),
        *_render_points(sub_theme.get("points")),
    ]


def _render_sub_themes(sub_themes: Any) -> list[str]:
    """Render a theme's critique points, tolerating a non-list value."""
    if not isinstance(sub_themes, list):
        return []
    lines: list[str] = []
    for sub_theme in sub_themes:
        lines.extend(_render_sub_theme(sub_theme))
    return lines


def _render_theme(theme: dict[str, Any]) -> list[str]:
    """Render one top-level theme: heading, prose, frequency, sub-themes.

    An entry with no name renders nothing at all -- an empty name used to
    reach the bolded-label formatter and print a doubled-asterisk ``****:``
    over orphaned text.

    The blank line before the sub-theme bullets is load-bearing: without
    it the theme's own prose and the first bullet are adjacent lines, and
    whether that starts a list or continues the paragraph is a renderer's
    choice rather than ours.
    """
    name = str(theme.get("theme") or "").strip()
    if not name:
        return []
    lines = [f"\n#### {name}\n"]
    description = str(theme.get("description") or "").strip()
    if description:
        lines.append(description)
    frequency = str(theme.get("frequency") or "").strip()
    if frequency:
        lines.append(f"*Frequency: {frequency}*")
    sub_themes = _render_sub_themes(theme.get("sub_themes"))
    if sub_themes:
        # Only when prose precedes them: the heading line already carries
        # its own trailing newline, so an unconditional separator would
        # print two blank lines under a theme that has no prose.
        lines.extend(["", *sub_themes] if len(lines) > 1 else sub_themes)
    return lines


def _render_theme_entry(theme: Any) -> list[str]:
    """Render one ``recurring_themes`` entry, dict or bare string."""
    if isinstance(theme, dict):
        return _render_theme(theme)
    text = str(theme).strip()
    return [f"\n#### {text}\n"] if text else []


def render_emerging_themes(meta_review: dict[str, Any]) -> list[str]:
    """Render 'Emerging themes' from the taxonomy, or from its fallback.

    Prefers ``recurring_themes`` (the full nested taxonomy); falls back to
    the flattened ``emerging_themes`` bare-name list when structured data
    is absent -- a demo/seed report, or one persisted before that field
    existed. The fallback stays a plain bullet list: bare names carry no
    hierarchy to show.

    Args:
        meta_review: The run's meta-review state dict.

    Returns:
        Markdown lines for the section, or an empty list when there is
        nothing to render.
    """
    themes = meta_review.get("recurring_themes")
    if not themes:
        return _render_bare_theme_names(meta_review.get("emerging_themes"))
    lines: list[str] = []
    for theme in themes:
        lines.extend(_render_theme_entry(theme))
    if not lines:
        return []
    return ["\n### Emerging themes\n", *lines]


def _render_bare_theme_names(emerging_themes: Any) -> list[str]:
    """Render the flattened name-only fallback as a plain bullet list."""
    if not isinstance(emerging_themes, list) or not emerging_themes:
        return []
    return ["\n### Emerging themes\n"] + [
        f"- {name}" for name in emerging_themes
    ]


class _RecommendationFields(NamedTuple):
    """One roadmap step, normalized from either published entry shape.

    ``strategic_recommendations`` entries are either a structured dict or
    (from before this schema existed) a bare string -- normalizing both
    into one shape here keeps ``_render_recommendation`` a plain
    formatter instead of a second isinstance branch.
    """

    body: str
    justification: str
    time_estimate: str
    phase_label: str
    recommended_idea: str


def _normalize_recommendation(
    rec: dict[str, Any] | str,
) -> _RecommendationFields:
    """Normalize one recommendation entry, dict or legacy bare string."""
    if not isinstance(rec, dict):
        return _RecommendationFields(str(rec), "", "", "", "")
    area = rec.get("focus_area", "")
    recommendation = rec.get("recommendation", "")
    body = f"**{area}**: {recommendation}" if area else str(recommendation)
    return _RecommendationFields(
        body=body,
        justification=str(rec.get("justification") or ""),
        # R14-8: the published roadmap's richer step shape -- a time
        # estimate, an optional lettered sub-phase, and which reviewed
        # idea a step selects (by hypothesis_index, never by echoing its
        # text -- see schemas/planning.py). Absent on a report persisted
        # before these fields existed, or an entry that carries none.
        time_estimate=str(rec.get("time_estimate") or "").strip(),
        phase_label=str(rec.get("phase_label") or "").strip(),
        recommended_idea=str(rec.get("recommended_idea") or "").strip(),
    )


def _render_recommendation(
    rec: dict[str, Any] | str, *, index: int | None = None
) -> list[str]:
    """Render one recommendation entry, as the primary lead or a roadmap step.

    ``index=None`` renders the lead line, labelled "Primary recommendation";
    an integer ``index`` renders it as that numbered roadmap step instead.
    """
    fields = _normalize_recommendation(rec)
    prefix = f"{fields.phase_label}: " if fields.phase_label else ""
    suffix = f" ({fields.time_estimate})" if fields.time_estimate else ""
    label = "**Primary recommendation:**" if index is None else f"{index}."
    lines = [f"{label} {prefix}{fields.body}{suffix}"]
    if fields.justification:
        lines.append(f"  *{fields.justification}*")
    if fields.recommended_idea:
        lines.append(f"  Recommended idea: {fields.recommended_idea}")
    return lines


def _render_bullet_list(heading: str, items: list[Any]) -> list[str]:
    """Render a heading and its bullet items, or nothing when empty."""
    if not items:
        return []
    return [f"\n{heading}\n"] + [f"- {item}" for item in items]


_META_REVIEW_BULLET_SECTIONS = (
    ("common_strengths", "### Common strengths"),
    ("common_weaknesses", "### Common weaknesses"),
)


# Legacy fixed field set: what a run's meta-review carried before the
# comparison axes became domain-aware. A report persisted (or, for an
# in-flight run, a checkpoint written) under the old schema still has this
# shape, not `axes`/`values`, so the renderers below accept either.
_IDEA_COMPARISON_FIELDS = (
    ("distinguishing_attribute", "Distinguishing attribute"),
    ("computational_scalability", "Computational scalability"),
    ("supporting_evidence_basis", "Supporting evidence basis"),
    ("primary_novelty_parameter", "Primary novelty parameter"),
)

_EXISTING_SOLUTION_FIELDS = (
    ("approach", "Approach"),
    ("sensitivity_to_novelty", "Sensitivity to novelty"),
    ("scalability", "Scalability"),
)


def _render_legacy_comparison_fields(
    entry: dict[str, Any], fields: tuple[tuple[str, str], ...]
) -> list[str]:
    """Render bullet lines for the pre-axes fixed field set."""
    lines = []
    for key, heading in fields:
        value = str(entry.get(key) or "").strip()
        if value:
            lines.append(f"  - **{heading}:** {value}")
    return lines


def _render_axis_values(axes: list[Any], values: Any) -> list[str]:
    """Render bullet lines pairing each axis with its positional value.

    ``values[i]`` rates the row on ``axes[i]`` (schemas/meta_review_schema.py's
    convention); a shorter list on either side simply pairs up to its own
    length rather than rendering an unlabeled value or raising.
    """
    if not isinstance(values, list):
        return []
    lines = []
    for axis, value in zip(axes, values, strict=False):
        axis_label = str(axis).strip()
        value_text = str(value).strip()
        if axis_label and value_text:
            lines.append(f"  - **{axis_label}:** {value_text}")
    return lines


def _render_idea_comparison(idea: Any, axes: list[Any]) -> list[str]:
    """Render one candidate-idea comparison row, or nothing when unlabeled.

    Prefers the domain-aware ``values`` shape, paired positionally against
    the table's own ``axes``; falls back to the older fixed field set
    (``_IDEA_COMPARISON_FIELDS``) for a run whose meta-review predates that.
    """
    if not isinstance(idea, dict):
        return []
    label = str(idea.get("idea") or "").strip()
    if not label:
        return []
    lines = [f"- **{label}**"]
    if axes and isinstance(idea.get("values"), list):
        lines += _render_axis_values(axes, idea["values"])
    else:
        lines += _render_legacy_comparison_fields(idea, _IDEA_COMPARISON_FIELDS)
    return lines


def _render_candidate_comparison(comparison: Any) -> list[str]:
    """Render 'Comparison of candidate ideas', or nothing when empty.

    Google's published report carries this comparison twice under the
    same title (R12-9): a thematic prose comparison (section 5) and a
    structured per-idea table (section 6). The table's columns follow the
    run's own subject matter (``axes``, chosen per run rather than fixed --
    a wet-lab biology idea has no use for "computational scalability"),
    rendered as a thematic summary paragraph plus one bullet block per
    idea, in the bold-label style every other section here uses (see
    ``_render_connection``) rather than a markdown table, which nothing in
    this renderer emits elsewhere.
    """
    if not isinstance(comparison, dict):
        return []
    summary = str(comparison.get("thematic_summary") or "").strip()
    axes = comparison.get("axes") or []
    idea_lines: list[str] = []
    for idea in comparison.get("ideas") or []:
        idea_lines += _render_idea_comparison(idea, axes)
    if not (summary or idea_lines):
        return []
    lines = ["\n### Comparison of candidate ideas\n"]
    if summary:
        lines += [summary, ""]
    lines += idea_lines
    return lines


def _render_existing_solution_row(row: Any, axes: list[Any]) -> list[str]:
    """Render one existing-solutions comparison row, or nothing when unnamed.

    Same axes/values-or-legacy-fields choice as ``_render_idea_comparison``.
    """
    if not isinstance(row, dict):
        return []
    label = str(row.get("method") or "").strip()
    if not label:
        return []
    lines = [f"- **{label}**"]
    if axes and isinstance(row.get("values"), list):
        lines += _render_axis_values(axes, row["values"])
    else:
        lines += _render_legacy_comparison_fields(
            row, _EXISTING_SOLUTION_FIELDS
        )
    return lines


def _render_existing_solutions_comparison(comparison: Any) -> list[str]:
    """Render 'Comparison to existing solutions', or nothing when empty.

    Empty (not just absent) is a real, expected case here: the prompt
    tells the model to leave this whole comparison out when the goal has
    no standard-of-care landscape to compare against (e.g. a basic
    mechanism question), rather than inventing one.
    """
    if not isinstance(comparison, dict):
        return []
    summary = str(comparison.get("summary") or "").strip()
    axes = comparison.get("axes") or []
    row_lines: list[str] = []
    for row in comparison.get("rows") or []:
        row_lines += _render_existing_solution_row(row, axes)
    if not (summary or row_lines):
        return []
    lines = ["\n### Comparison to existing solutions\n"]
    if summary:
        lines += [summary, ""]
    lines += row_lines
    return lines


def _render_strategic_recommendations(recs: list[Any]) -> list[str]:
    """Render 'Recommendation and strategic roadmap', or nothing when empty.

    Google's published section 9 (R12-11) sequences a named primary
    recommendation through four named phases, each with concrete next
    steps. Our ``strategic_recommendations`` carries no phase name,
    dependency, or ordering field beyond list position -- it is a flat
    ``{focus_area, recommendation, justification}`` list -- so named
    phases with assays would be invented content the schema cannot
    support. This distinguishes the first entry as the primary
    recommendation and numbers the rest as roadmap steps, the
    presentation the data actually carries.
    """
    if not recs:
        return []
    lines = ["\n### Recommendation and strategic roadmap\n"]
    lines += _render_recommendation(recs[0])
    for i, rec in enumerate(recs[1:], start=1):
        lines += _render_recommendation(rec, index=i)
    return lines


def _render_related_hypotheses(related: list[str]) -> list[str]:
    """Render the 'Related hypotheses' bullet block for one connection."""
    if not related:
        return ["- **Related hypotheses:** (unspecified)"]
    return ["- **Related hypotheses:**"] + [f"  - {h}" for h in related]


def _render_connection(connection: Any) -> list[str]:
    """Render one potential-connection entry, or nothing when malformed."""
    if not isinstance(connection, dict):
        return []
    related = [str(h) for h in connection.get("related_hypotheses") or []]
    kind = str(connection.get("connection_type") or "")
    opportunity = str(connection.get("synthesis_opportunity") or "")
    if not (related or kind or opportunity):
        return []
    lines = _render_related_hypotheses(related)
    if kind:
        lines.append(f"  - **Connection type:** {kind}")
    if opportunity:
        lines.append(f"  - **Synthesis opportunity:** {opportunity}")
    return lines


def _render_unexpected_connections(connections: list[Any]) -> list[str]:
    """Render 'Unexpected connections', or nothing when empty."""
    lines: list[str] = []
    for connection in connections:
        lines += _render_connection(connection)
    if not lines:
        return []
    return ["\n### Unexpected connections\n", *lines]


def _render_main_research_directions_markdown(
    meta_review: dict[str, Any],
) -> list[str]:
    """Render "Main Research Directions" (R14-27), right before Top hypotheses.

    Google's published ranking report carries its own narrative synthesis
    here -- two flowing prose paragraphs weaving the run's directions
    together (``top-ranking-hypotheses.md:24-28``), distinct from the
    itemized per-direction array the earlier research-overview sub-sections
    render (``report/markdown/overview.py::_render_directions_list``). The
    ``meta_review.main_research_directions`` string already carries any
    internal paragraph break the model wrote (schemas/meta_review_schema.py
    asks for two, separated by a blank line), so this renders it verbatim
    rather than re-splitting it.

    Skips cleanly -- no bare heading -- when the field is absent or blank:
    a legacy run persisted before this field existed, or a provider
    response that omits it under json_object mode.
    """
    text = str(meta_review.get("main_research_directions") or "").strip()
    if not text:
        return []
    return ["## Main Research Directions\n", text, ""]


def _render_meta_review_overview_markdown(
    meta_review: dict[str, Any],
) -> list[str]:
    """Render the report's earlier meta-review insights section.

    Cross-run synthesis -- common strengths/weaknesses, recurring themes,
    and unexpected connections -- positioned before the research-overview
    sub-sections, matching Google's own "meta-review-style synthesis"
    placement. The tournament-facing half of this same payload (candidate
    comparison, existing-solutions comparison, the recommendation roadmap)
    renders separately, under its own heading further down -- see
    ``_render_meta_review_ranking_markdown``.

    A truthy ``meta_review`` dict with nothing this half renders (every
    field belongs to the other half instead) emits no heading -- R14-23:
    no section prints an empty heading over nothing.
    """
    if not meta_review:
        return []
    body: list[str] = []
    body += _render_optional_paragraph(meta_review.get("summary"))
    for section_key, heading in _META_REVIEW_BULLET_SECTIONS:
        body += _render_bullet_list(heading, meta_review.get(section_key) or [])
    body += render_emerging_themes(meta_review)
    body += _render_unexpected_connections(
        meta_review.get("potential_connections") or []
    )
    if not body:
        return []
    return ["\n## Meta-review insights\n", *body]


def _render_meta_review_ranking_markdown(
    meta_review: dict[str, Any],
) -> list[str]:
    """Render the report's later, tournament-facing meta-review section.

    The candidate comparison ("Idea Comparison Table"), the existing-
    solutions comparison, and the recommendation roadmap
    ("Recommendation") -- positioned after Top hypotheses, the candidates
    these sections compare. Titled "Comparison and Recommendation" rather
    than reusing ``_render_meta_review_overview_markdown``'s "Meta-review
    insights" heading: both halves are equally "insights the meta-review
    agent produced", but with both now in one document, one heading text
    stated twice would mislead a reader (and a table-of-contents reader)
    into thinking the second occurrence repeats the first.

    Same empty-body guard as the overview half, above: a run with a
    meta-review summary but no tournament comparison (the common case for
    a small pool) must not leave a bare "Comparison and Recommendation"
    heading over nothing.
    """
    if not meta_review:
        return []
    body: list[str] = []
    body += _render_candidate_comparison(
        meta_review.get("candidate_comparison")
    )
    body += _render_existing_solutions_comparison(
        meta_review.get("existing_solutions_comparison")
    )
    body += _render_strategic_recommendations(
        meta_review.get("strategic_recommendations") or []
    )
    if not body:
        return []
    return ["\n## Comparison and Recommendation\n", *body]
