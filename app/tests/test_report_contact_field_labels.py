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

from app.report.markdown.overview import render_research_overview_markdown


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


def test_expertise_is_the_one_field_no_exemplar_supports() -> None:
    """RESEARCH-CONTACTS-FIELDS-001: ``expertise`` has no corpus source.

    A full survey of every published research-contacts exemplar --
    Figure A.22 (paper App. A, the narrowest: a Research Direction
    heading, researcher name(s), one free-text relevance paragraph, no
    ``Justification:`` label at all), the 14/19 protein-assemblies
    hypothesis files R14-16 draws from (a per-researcher
    ``Justification:`` plus one varying evidence field, 2-4 observable
    fields depending on the file), and the same corpus's grouped
    ``reports/research-overview.md`` (no per-contact ``Justification:``
    at all -- one shared "Why they are best for this direction:"
    rationale per group instead) -- finds no field anywhere naming a
    researcher's area of expertise separately from that relevance/
    justification prose. ``expertise`` is this schema's one field with
    no exemplar behind it (``schemas/synthesis.py``'s
    ``research_contacts[].expertise``).

    It renders anyway: removing it needs a schema/prompt change in
    ``agents/meta_review/research_overview_contacts.py``, out of this
    row's rendering-only scope. This pins that deliberate choice so a
    later change notices it rather than silently dropping real model
    output, and guards against a *second* unsupported field being added
    beside it without the same review.
    """
    markdown = _markdown(
        [
            {
                "candidate_id": "author-1-1",
                "name": "Ada Researcher",
                "expertise": "Biofilm metabolism",
                "justification": "Authored the analyzed source.",
                "research_direction": "Direction one",
            }
        ]
    )

    assert "**Relevant expertise:** Biofilm metabolism" in markdown
    # candidate_id is unrendered provenance (anti-hallucination selection
    # against a verified candidate list), never shown to the reader.
    assert "author-1-1" not in markdown
    # The full labelled-field set stays exactly these four; a fifth
    # label appearing here means a new field was added without updating
    # this pin (and the row's residual in docs/PARITY.md).
    for label in (
        "Research direction:",
        "Relevant expertise:",
        "Justification:",
    ):
        assert markdown.count(label) == 1
    assert "Supporting article:" not in markdown
