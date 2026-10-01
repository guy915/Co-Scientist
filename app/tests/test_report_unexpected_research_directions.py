"""Task B: 'Unexpected research directions' renders in the overview.

MASH's own published exemplar carries a fourth block, ``Unexpected
Research Directions``, directly beneath its expanded restatement of the
five main directions (``docs/CORPUS-EXTRACTION.md``, .../mash-liver-
fibrosis-reversal-therapeutic-hypothesis.md:418) -- three bolded-name-
plus-prose bullets naming genuinely novel strategic directions, not a
repeat of the main research_directions and not the same thing as
``unexpected_patterns`` (R12-10, a pattern observed across the ideas,
not a direction worth pursuing).
"""

from app.report.markdown.overview import render_research_overview_markdown


def _markdown(payload: dict[str, object]) -> str:
    """Render the overview payload to a single markdown string."""
    return "\n".join(render_research_overview_markdown(payload))


def test_unexpected_directions_render_as_bolded_name_plus_prose_bullets() -> (
    None
):
    """Each entry renders its title bolded, followed by its prose."""
    markdown = _markdown(
        {
            "overview": {
                "summary": "S",
                "research_directions": [
                    {"title": "A", "importance": "I"},
                    {"title": "B", "importance": "I"},
                ],
            },
            "unexpected_research_directions": [
                {
                    "title": "Nuclear LOXL2 as a Histone Modifier",
                    "description": (
                        "Beyond crosslinking collagen, nuclear-translocated"
                        " LOXL2 may act as a histone aminooxidase."
                    ),
                }
            ],
        }
    )

    assert "### Unexpected research directions" in markdown
    assert (
        "- **Nuclear LOXL2 as a Histone Modifier:** Beyond crosslinking"
        " collagen, nuclear-translocated LOXL2 may act as a histone"
        " aminooxidase."
    ) in markdown


def test_section_sits_adjacent_to_the_directions_content() -> None:
    """The block renders inside 'Research Overview', after the directions."""
    markdown = _markdown(
        {
            "overview": {
                "summary": "S",
                "research_directions": [{"title": "A", "importance": "I"}],
            },
            "unexpected_research_directions": [
                {"title": "X", "description": "Y"}
            ],
        }
    )

    overview_index = markdown.index("## Research Overview")
    directions_index = markdown.index("### A")
    unexpected_index = markdown.index("### Unexpected research directions")
    open_questions_index = markdown.find("## Open questions")

    assert overview_index < directions_index < unexpected_index
    # Still inside the Research Overview section, not the next one.
    assert open_questions_index == -1 or unexpected_index < open_questions_index


def test_no_unexpected_directions_renders_no_heading() -> None:
    """Absent/empty field emits no heading -- legacy runs must not regress."""
    markdown = _markdown(
        {"overview": {"summary": "S", "research_directions": []}}
    )

    assert "Unexpected research directions" not in markdown


def test_an_entry_with_no_description_still_renders_its_title() -> None:
    """Degrade, never drop -- a bare title bullet with no colon."""
    markdown = _markdown(
        {
            "overview": {"summary": "S", "research_directions": []},
            "unexpected_research_directions": [{"title": "Bare title"}],
        }
    )

    assert "- Bare title" in markdown
    assert "- **Bare title:**" not in markdown


def test_a_json_string_description_is_flattened() -> None:
    """Matches this module's established json_object-downgrade coercion."""
    markdown = _markdown(
        {
            "overview": {"summary": "S", "research_directions": []},
            "unexpected_research_directions": [
                {
                    "title": "X",
                    "description": '{"claim": "worth pursuing"}',
                }
            ],
        }
    )

    assert "worth pursuing" in markdown
    assert '{"claim"' not in markdown
