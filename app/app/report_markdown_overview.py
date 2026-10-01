"""Research-overview markdown renderers for the report.

Renders the engine's ``research_overview`` payload — the overview summary
and research directions, the NIH Specific Aims section, and the research
contacts — as markdown lines. Split from ``report_markdown`` by concern;
every function here is pure.
"""

from __future__ import annotations

from typing import Any

# R14-6: the research-contacts renderers (flat and grouped-by-direction)
# live in report_markdown_contact_groups -- split out to keep this module
# within the size cap, and a leaf relative to this one (it imports only
# report_markdown_text, never this module) so the two never form a
# cross-import cycle. The grouped renderer is re-exported so this module's
# namespace keeps resolving.
from app.report_markdown_contact_groups import (
    _render_research_contacts_section as _render_research_contacts_section,
)

# The malformed-field text coercion is a leaf module shared with
# report_markdown_contact_groups (R14-6); both names are re-exported so
# this module's namespace keeps resolving.
from app.report_markdown_text import _readable_text as _readable_text
from app.report_markdown_text import (
    _readable_text_list as _readable_text_list,
)


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
    """Render a compact preview list naming each direction, or nothing.

    MO-12: both published exemplars front-load a named preview list ahead
    of the full per-direction detail that follows (ALS: "We will be
    focusing on these interrelated areas"; cf-PICI: "Main Research
    Directions"). Titles only, no new model output -- naming each
    direction rather than repeating its prose avoids duplicating the
    paragraphs the full detail below already carries.

    Renders nothing below two named directions: a "preview" of a single
    entry duplicates it rather than orienting the reader.
    """
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
    ``_render_evaluation_criterion`` (report_markdown_supervisor.py)
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
    """Render 'Unexpected research directions', or [] when nothing usable.

    Task B: MASH's own published exemplar carries this as a fourth block
    directly beneath its expanded restatement of the five main research
    directions -- genuinely new strategic directions, not a repeat of
    ``research_directions`` above and not ``unexpected_patterns``
    (R12-10, a pattern observed *across the ideas*, not a direction worth
    pursuing). Rendered adjacent to the directions content, inside this
    same "## Research Overview" section, by the caller below.
    """
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
    ``report_markdown_meta_review._render_bullet_list``: that module
    already imports from this one (``_render_optional_paragraph``), and
    importing back would be circular.
    """
    values = _readable_text_list(items)
    if not values:
        return []
    return [f"\n{heading}\n"] + [f"- {v}" for v in values]


def _render_open_questions_section(payload: dict[str, Any]) -> list[str]:
    """Render 'Open questions' plus its Clear/Unexpected patterns pair.

    R12-10: the published report's top-level ``Open Questions``, ``Clear
    Patterns:``, and ``Unexpected Patterns:`` sections. Google's second
    exemplar (R14-1) lists ``Open questions`` beside the research-
    directions summary in the same document family this overview
    renders, so it lands here rather than beside the ``meta_review``-
    sourced ``Unexpected connections`` section one level up.
    """
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
    """Return the overview's four optional sub-sections, each its own list.

    Split out of ``render_research_overview_markdown`` so the report's
    table of contents (R14-1) can tell which of these actually rendered
    without re-deriving the guard logic, and without scanning arbitrary
    field prose for a false '## ' match -- each returned list either is
    empty or leads with that sub-section's own heading.

    Args:
        overview: The engine ``research_overview`` payload, shaped as
            ``{"overview": {...}, "nih_specific_aims": {...}}``. May be empty
            or carry empty sub-dicts for runs without hypotheses.
        hypothesis_title_by_id: This run's persisted hypothesis titles by
            id (R14-6), for resolving a research-contact-group's example
            hypotheses. Omitted where the caller has none -- those
            examples then simply do not render.

    Returns:
        Four lists, in document order: Research Overview, Open questions,
        NIH Specific Aims, Research Contacts. Any of them is empty when
        that sub-section has nothing to render.
    """
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
