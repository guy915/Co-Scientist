"""Research contacts retain their fields and direction groups."""

from app.report.markdown.overview import render_research_overview_markdown


def _markdown(
    contacts: list[dict[str, object]],
    groups: list[dict[str, object]] | None = None,
    hypothesis_title_by_id: dict[str, str] | None = None,
) -> str:
    """Render an overview payload carrying only the given contacts/groups."""
    payload: dict[str, object] = {"research_contacts": contacts}
    if groups is not None:
        payload["research_contact_groups"] = groups
    return "\n".join(
        render_research_overview_markdown(payload, hypothesis_title_by_id)
    )


def test_a_group_heading_and_rationale_render() -> None:
    """The group's own heading and shared rationale print once."""
    markdown = _markdown(
        contacts=[
            {
                "name": "Ada Researcher",
                "expertise": "Chromatin biology",
                "justification": "Authored the analyzed source.",
                "research_direction": "Epigenetic control of fibrosis",
            },
        ],
        groups=[
            {
                "research_direction": "Epigenetic control of fibrosis",
                "rationale": "Both bring complementary expertise.",
            }
        ],
    )

    assert "### Epigenetic control of fibrosis" in markdown
    assert (
        "**Why they are best for this direction:** Both bring"
        " complementary expertise." in markdown
    )
    assert "#### Ada Researcher" in markdown
    # Grouped, so the per-contact direction line is not repeated.
    assert "**Research direction:**" not in markdown


def test_a_group_with_two_contacts_lists_both_beneath_it() -> None:
    """Every contact tagged with a group's direction nests under it."""
    markdown = _markdown(
        contacts=[
            {"name": "Ada Researcher", "research_direction": "Direction A"},
            {"name": "Bo Scientist", "research_direction": "Direction A"},
        ],
        groups=[{"research_direction": "Direction A", "rationale": "Why."}],
    )

    heading_index = markdown.index("### Direction A")
    ada_index = markdown.index("#### Ada Researcher")
    bo_index = markdown.index("#### Bo Scientist")
    assert heading_index < ada_index
    assert heading_index < bo_index


def test_example_hypothesis_titles_resolve_by_id() -> None:
    """Example hypotheses render the real persisted title, not an id."""
    markdown = _markdown(
        contacts=[
            {"name": "Ada Researcher", "research_direction": "Direction A"}
        ],
        groups=[
            {
                "research_direction": "Direction A",
                "rationale": "Why.",
                "example_hypothesis_ids": ["h1", "h2", "missing"],
            }
        ],
        hypothesis_title_by_id={
            "h1": "HDAC inhibition reverses fibrosis",
            "h2": "SIRT1 activation blocks collagen deposition",
        },
    )

    assert "**Example Hypothesis Titles:**" in markdown
    assert "- HDAC inhibition reverses fibrosis" in markdown
    assert "- SIRT1 activation blocks collagen deposition" in markdown
    # An id with no resolvable title is dropped, never shown as a raw id.
    assert "missing" not in markdown


def test_no_example_titles_omits_the_bullet_heading() -> None:
    """A group with no resolvable example hypotheses has no titles block."""
    markdown = _markdown(
        contacts=[
            {"name": "Ada Researcher", "research_direction": "Direction A"}
        ],
        groups=[{"research_direction": "Direction A", "rationale": "Why."}],
    )

    assert "Example Hypothesis Titles" not in markdown


def test_a_contact_matching_no_group_falls_back_to_the_flat_shape() -> None:
    """MO-7's original rendering is unchanged for an unmatched contact."""
    markdown = _markdown(
        contacts=[
            {
                "name": "Cy Unaffiliated",
                "expertise": "Independent review",
                "justification": "Cited widely in this area.",
                "research_direction": "Direction Z",
            }
        ],
        groups=[{"research_direction": "Direction A", "rationale": "Why."}],
    )

    assert "### Cy Unaffiliated" in markdown
    assert "**Research direction:** Direction Z" in markdown
    assert "Direction A" not in markdown


def test_a_report_with_no_groups_field_is_unaffected() -> None:
    """A report persisted before R14-6 renders exactly as MO-7 always did."""
    markdown = _markdown(
        contacts=[
            {
                "name": "Ada Researcher",
                "expertise": "Chromatin biology",
                "justification": "Authored the analyzed source.",
                "research_direction": "Epigenetic control of fibrosis",
            }
        ]
    )

    assert "### Ada Researcher" in markdown
    assert "**Research direction:** Epigenetic control of fibrosis" in markdown
    assert "Why they are best for this direction" not in markdown


def test_a_group_naming_no_matching_contact_renders_nothing() -> None:
    """A group the model wrote for a direction no contact carries is empty."""
    markdown = _markdown(
        contacts=[
            {"name": "Ada Researcher", "research_direction": "Direction A"}
        ],
        groups=[
            {"research_direction": "Direction Never Tagged", "rationale": "X"}
        ],
    )

    assert "Direction Never Tagged" not in markdown
    assert "### Direction A" not in markdown
    assert "### Ada Researcher" in markdown


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
