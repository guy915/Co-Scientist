"""MO-2: the "Emerging themes" section renders the full theme taxonomy.

``recurring_themes[].{theme, description, frequency}`` is a five-theme,
two-to-three-level taxonomy in Google's published meta-review critique
(``meta-review-critiques/als-meta-review-critique.md``). The engine's
schema already flattens that structure to a list of objects (an accepted
adaptation), but ``meta_review.py`` used to drop ``description`` and
``frequency`` before the state dict reached the app, so this section
printed bare theme names -- the fields were computed by the model, paid
for in tokens, and thrown away. These pin that the renderer now uses them
when present, and still degrades cleanly to the old bare-name bullets for
a report that only carries the flattened ``emerging_themes`` list (a demo
scenario, or a report persisted before this field existed).
"""

from app import report_markdown


def _markdown(meta_review: dict[str, object]) -> str:
    """Render a minimal report carrying only the given meta-review."""
    hypothesis: dict[str, object] = {
        "id": "h1",
        "title": "NHE1 coupling",
        "statement": "NHE1 couples to the RSK axis in HFpEF.",
    }
    return report_markdown.render_overview_document_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[hypothesis],
            meta_review=meta_review,
        )
    )


def test_a_structured_theme_renders_its_description_and_frequency() -> None:
    """A recurring_themes entry prints its description and frequency."""
    markdown = _markdown(
        {
            "recurring_themes": [
                {
                    "theme": "Motor neuron specificity",
                    "description": (
                        "Ideas rarely explain why the mechanism would"
                        " preferentially affect motor neurons."
                    ),
                    "frequency": "common",
                }
            ]
        }
    )

    assert "### Emerging themes" in markdown
    assert "Motor neuron specificity" in markdown
    assert "preferentially affect motor neurons" in markdown
    assert "common" in markdown


def test_a_bare_theme_name_falls_back_to_a_plain_bullet() -> None:
    """A report with only the flattened list still renders, bare-named.

    Covers demo/seed reports and any report persisted before
    ``recurring_themes`` existed -- ``emerging_themes`` alone must not
    regress to a missing section.
    """
    markdown = _markdown(
        {"emerging_themes": ["Time-resolved state measurements"]}
    )

    assert "### Emerging themes" in markdown
    assert "- Time-resolved state measurements" in markdown


def test_an_entry_with_no_theme_name_is_skipped() -> None:
    """A malformed entry with an empty theme does not render a bare '****:'.

    ``**:`` alone is too loose a check -- R14-13's per-hypothesis disclaimer
    ("**About**: ...") legitimately contains it. The bug this guards is an
    empty name reaching ``f"**{name}**: {description}"`` and rendering the
    doubled-asterisk ``****:`` that produces.
    """
    markdown = _markdown(
        {
            "recurring_themes": [
                {"theme": "", "description": "orphaned text", "frequency": ""}
            ]
        }
    )

    assert "orphaned text" not in markdown
    assert "****:" not in markdown
