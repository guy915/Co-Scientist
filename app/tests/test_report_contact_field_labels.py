"""R14-16: research contacts render two named fields, not one free-text one.

``Justification:`` is consistent across all 14 published research contacts
that carry it (docs/CORPUS-EXTRACTION.md R14-16); a second, evidence-citing
field follows with a label that varies freely across the sample. This pins
the fixed labels the renderer now uses for both -- the consistent
``Justification:`` mirrored directly, and ``Supporting article:`` chosen
for the varying one, since this schema's version of that field is always
a single grounded paper (``source_title``/``source_url``), never free
citation prose.
"""

from app.report_markdown_overview import render_research_overview_markdown


def _markdown(contacts: list[dict[str, object]]) -> str:
    return "\n".join(
        render_research_overview_markdown({"research_contacts": contacts})
    )


def test_justification_renders_under_its_published_label() -> None:
    markdown = _markdown(
        [
            {
                "name": "Ada Researcher",
                "justification": "Authored the analyzed source.",
            }
        ]
    )

    assert "**Justification:** Authored the analyzed source." in markdown


def test_the_evidence_citing_field_renders_under_a_fixed_name() -> None:
    markdown = _markdown(
        [
            {
                "name": "Ada Researcher",
                "justification": "Authored the analyzed source.",
                "source_title": "A biofilm study",
                "source_url": "https://example.org/paper",
            }
        ]
    )

    assert (
        "**Supporting article:** [A biofilm study]"
        "(https://example.org/paper)" in markdown
    )
    assert "Evidence:" not in markdown


def test_an_unsourced_contact_renders_no_supporting_article_line() -> None:
    markdown = _markdown(
        [{"name": "Ada Researcher", "justification": "Relevant background."}]
    )

    assert "Supporting article" not in markdown
