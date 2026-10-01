"""R12-10: open questions and cross-cutting patterns render in the overview.

The MASH Goal Report carries top-level ``Open Questions``, ``Clear
Patterns:``, and ``Unexpected Patterns:`` sections
(``docs/CORPUS-EXTRACTION.md`` R12-10). The research-overview synthesis --
the terminal cross-hypothesis narrative -- is the natural home: Google's own
second exemplar (``research-overview.md``, R14-1) lists ``Open questions``
beside its research-directions summary in that same document family, one
level up from where our ``Unexpected connections``/``Recommendation``
sections already live in ``meta_review``.
"""

from app.report.markdown.overview import render_research_overview_markdown


def _markdown(payload: dict[str, object]) -> str:
    """Render the overview payload to a single markdown string."""
    return "\n".join(render_research_overview_markdown(payload))


def test_open_questions_render_as_a_numbered_list() -> None:
    """Each open question numbers from 1, matching the published list."""
    markdown = _markdown(
        {
            "open_questions": [
                "To what extent can X be targeted to reverse Y?",
                "How does the crosstalk between A and B modulate C?",
            ]
        }
    )

    assert "## Open questions" in markdown
    assert "1. To what extent can X be targeted to reverse Y?" in markdown
    assert "2. How does the crosstalk between A and B modulate C?" in markdown


def test_clear_and_unexpected_patterns_render_as_labelled_bullet_lists() -> (
    None
):
    """Both pattern lists render under their own published-name headings."""
    markdown = _markdown(
        {
            "clear_patterns": ["Lipid handling recurs across every idea."],
            "unexpected_patterns": [
                "A metabolic block explains a proteolysis failure."
            ],
        }
    )

    assert "### Clear patterns" in markdown
    assert "Lipid handling recurs across every idea." in markdown
    assert "### Unexpected patterns" in markdown
    assert "A metabolic block explains a proteolysis failure." in markdown


def test_no_open_questions_or_patterns_renders_no_section() -> None:
    """Absent/empty fields emit no heading -- ours, not Google's convention."""
    markdown = _markdown({"overview": {"summary": "S"}})

    assert "Open questions" not in markdown
    assert "Clear patterns" not in markdown
    assert "Unexpected patterns" not in markdown


def test_a_json_string_open_question_is_flattened() -> None:
    """Matches this module's established json_object-downgrade coercion."""
    markdown = _markdown({"open_questions": ['{"question": "What drives X?"}']})

    assert "What drives X?" in markdown
    assert '{"question"' not in markdown
