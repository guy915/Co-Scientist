"""MO-7: research contacts render the research direction that surfaced them.

Google's published exemplar tags each contact with
``Research Direction: X``, tying the researcher back to the direction that
surfaced them (``research-overviews/als-research-overview-and-contact.md``,
``docs/CORPUS-EXTRACTION.md`` MO-7). ``research_contacts[]`` had flattened
to a name, expertise, and justification with no such linkage. The engine
now carries ``research_direction`` through ``_validate_research_contacts``;
this pins that the renderer surfaces it, and degrades cleanly for a report
persisted before the field existed.
"""

from app.report.markdown.overview import render_research_overview_markdown


def _markdown(contacts: list[dict[str, object]]) -> str:
    """Render an overview payload carrying only the given contacts."""
    return "\n".join(
        render_research_overview_markdown({"research_contacts": contacts})
    )


def test_a_contact_renders_its_research_direction() -> None:
    """The linkage prints alongside the contact's expertise."""
    markdown = _markdown(
        [
            {
                "name": "Ada Researcher",
                "expertise": "Mitochondrial base excision repair",
                "justification": "Authored the analyzed source.",
                "research_direction": (
                    "Oxidative DNA Damage & Mitochondrial Base Excision"
                    " Repair (BER) in ALS"
                ),
            }
        ]
    )

    assert (
        "**Research direction:** Oxidative DNA Damage & Mitochondrial Base"
        " Excision Repair (BER) in ALS" in markdown
    )


def test_a_contact_with_no_research_direction_omits_the_line() -> None:
    """A report persisted before this field existed still renders cleanly."""
    markdown = _markdown(
        [
            {
                "name": "Ada Researcher",
                "expertise": "Mitochondrial base excision repair",
                "justification": "Authored the analyzed source.",
            }
        ]
    )

    assert "Research direction" not in markdown
    assert "Ada Researcher" in markdown
