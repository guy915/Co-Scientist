"""Report table-of-contents rendering.

R14-1: Google's published ``research-overview.md`` opens with an explicit
``#### Table of contents:`` section naming six of its own top-level
sections as bulleted nav items (docs/CORPUS-EXTRACTION.md R14-1). Our
combined report renders a different, run-dependent set of top-level
sections -- each independently conditional (R14-23: a section prints
nothing, heading included, when it has nothing to say) -- so mirroring
Google's fixed six items verbatim would as often as not point the reader
at a heading this render never produced, which is worse than no nav list
at all. The heading text and level carry over unchanged (structural, not
branded); the bulleted items are always this run's own populated
sections, in the order they render.
"""

from __future__ import annotations


def _section_heading(section: list[str]) -> str | None:
    """Return one section's own leading '## ' heading text, or None.

    Checked against only the section's first non-blank element -- several
    sections lead with a blank string or an embedded newline to control
    spacing before their own heading, but none put anything else ahead of
    it. Scanning every line instead of just this one would risk mistaking
    a model-authored field for a section heading: several hypothesis and
    overview fields render as bare LLM prose (``introduction``,
    ``recent_findings``, a contact's ``justification``, ...), and nothing
    in a json_object response constrains that prose from opening with its
    own "## " line.
    """
    for line in section:
        text = line.strip()
        if not text:
            continue
        return text[3:].strip() if text.startswith("## ") else None
    return None


def _render_table_of_contents(sections: list[list[str]]) -> list[str]:
    """Render the nav list of every section this render actually produced.

    Args:
        sections: Every top-level section's rendered lines, in document
            order -- populated or not; emptiness is checked here.

    Returns:
        The ``#### Table of contents:`` block, or nothing when no section
        rendered a heading (a report with nothing to navigate needs no
        navigation aid).
    """
    labels = [
        heading
        for section in sections
        if (heading := _section_heading(section)) is not None
    ]
    if not labels:
        return []
    lines = ["#### Table of contents:", ""]
    lines += [f"- {label}" for label in labels]
    lines.append("")
    return lines
