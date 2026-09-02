"""R14-6: research contacts render grouped by research direction.

Google's published exemplar groups research_contacts under the research
direction that surfaced them (4 groups in the corpus run), each group
carrying one shared "Why they are best for this direction" rationale
paragraph and two "Example Hypothesis Titles" (docs/CORPUS-EXTRACTION.md
R14-6). MO-7 (done) only restored the flat per-contact research_direction
tag. This pins the grouped rendering, and that a report carrying no
research_contact_groups -- an old report, or a response that never
populated it -- still renders MO-7's flat shape unchanged.
"""

from app.report_markdown_overview import render_research_overview_markdown


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
