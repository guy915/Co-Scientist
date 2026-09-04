"""R12-17: the report renders the Supervisor's synthesized attributes.

The published MASH plan prints its run Attributes at the top of the
report, as named rating scales: four carrying a 1-5 scale with worked
anchor examples, plus one categorical scale with a fixed value set
(``docs/CORPUS-EXTRACTION.md`` R12-17, Appendix C). The Supervisor already
synthesizes this shape as ``config_synthesis.attributes`` and
``prompts/review.py`` already injects it into every reviewer prompt as
"Stratification attributes (score each 1-5)" -- but nothing ever rendered
it to the reader. This pins that the markdown export now does, under a
heading distinct from the run's user-authored "Attributes" bullet list
under "Research Goal Details" (a different, plain-string field -- see the
CORPUS-EXTRACTION.md mirror-pass-1 vocabulary warning: "Attributes" names
two differently-shaped things in Google's own documents, and conflating
them would reproduce the wrong one).
"""

from app import report_markdown


def _markdown(
    attributes: list[dict[str, object]] | None,
    setup: dict[str, object] | None = None,
) -> str:
    """Render a minimal report carrying only the given attributes."""
    hypothesis: dict[str, object] = {
        "id": "h1",
        "title": "NHE1 coupling",
        "statement": "NHE1 couples to the RSK axis in HFpEF.",
    }
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[hypothesis],
            attributes=attributes,
            setup=setup,
        )
    )


def test_attributes_render_as_named_rating_scales() -> None:
    """Each synthesized attribute prints its name and 1-5 rubric."""
    markdown = _markdown(
        [
            {
                "name": "Mechanism Novelty",
                "rubric": (
                    "1: Well-established pathway, 3: New application of a"
                    " known mechanism, 5: Highly novel and"
                    " paradigm-shifting."
                ),
            },
            {
                "name": "Target Area",
                "rubric": (
                    "Categorize the primary focus of the hypothesis"
                    " (Epigenetics, Stellate Cell Biology, or"
                    " Stromal-Immune Crosstalk)."
                ),
            },
        ]
    )

    assert "## Stratification Attributes" in markdown
    assert "Mechanism Novelty" in markdown
    assert "Highly novel and paradigm-shifting." in markdown
    assert "Target Area" in markdown
    assert "Stromal-Immune Crosstalk" in markdown


def test_no_attributes_renders_no_section() -> None:
    """An absent attributes list emits no heading, not an empty one."""
    assert "Stratification Attributes" not in _markdown(None)
    assert "Stratification Attributes" not in _markdown([])


def test_an_attribute_with_no_name_is_skipped() -> None:
    """A malformed attribute with no name contributes nothing renderable."""
    markdown = _markdown([{"rubric": "orphaned rubric text"}])

    assert "orphaned rubric text" not in markdown
    assert "Stratification Attributes" not in markdown


def test_distinct_from_the_user_authored_attributes_list() -> None:
    """The synthesized section never replaces the user-authored list.

    It coexists with the user-authored "Attributes" bullet list rendered
    under "Research Goal Details"
    -- same English word, two different published sections, see the
    module docstring's vocabulary warning.
    """
    markdown = _markdown(
        [{"name": "Human Relevance", "rubric": "1-5 scale rubric text."}],
        setup={"attributes": ["Should be testable in human tissue"]},
    )

    assert "## Stratification Attributes" in markdown
    assert "Human Relevance" in markdown
    assert "**Attributes:**" in markdown
    assert "Should be testable in human tissue" in markdown
