"""R12-9: candidate ideas render as a cross-idea comparison section.

The MASH Goal Report carries two same-titled ``Comparison of Candidate
Ideas`` sections (``docs/CORPUS-EXTRACTION.md`` R12-9): a thematic prose
comparison (section 5, three subsections grouping ideas by mechanism and
arguing which is best supported) and a structured per-idea table (section
6, whose real column vocabulary -- Idea / Key Distinguishing Attribute /
Computational Scalability / Supporting Evidence Basis / Primary Novelty
Parameter -- a second published exemplar corroborates, R14-7). The two
sections are the same comparison in two forms, not a duplication error.

Our renderer folds both forms into one ``### Comparison of candidate
ideas`` section -- a thematic summary paragraph plus one block per idea --
rather than two duplicate headings, and renders each idea's columns as
bold-label bullets rather than a markdown table, matching every other
meta-review section's convention (``_render_connection``, ``_render_theme``)
instead of the published table markup.
"""

from app import report_markdown


def _markdown(meta_review: dict[str, object]) -> str:
    """Render a minimal report carrying only the given meta-review."""
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
            meta_review=meta_review,
        )
    )


def test_a_populated_comparison_renders_summary_and_idea_columns() -> None:
    """The thematic summary and every real R14-7 column name render."""
    markdown = _markdown(
        {
            "candidate_comparison": {
                "thematic_summary": (
                    "The ideas split into two mechanistic themes."
                ),
                "ideas": [
                    {
                        "idea": "Hypothesis 1: NHE1 blockade",
                        "distinguishing_attribute": (
                            "Targets an established clinical checkpoint."
                        ),
                        "computational_scalability": "Low compute burden.",
                        "supporting_evidence_basis": (
                            "Human scRNA-seq co-localization."
                        ),
                        "primary_novelty_parameter": (
                            "First to link NHE1 to RSK in this context."
                        ),
                    }
                ],
            }
        }
    )

    assert "### Comparison of candidate ideas" in markdown
    assert "The ideas split into two mechanistic themes." in markdown
    assert "Hypothesis 1: NHE1 blockade" in markdown
    assert "Targets an established clinical checkpoint." in markdown
    assert "Low compute burden." in markdown
    assert "Human scRNA-seq co-localization." in markdown
    assert "First to link NHE1 to RSK in this context." in markdown


def test_no_candidate_comparison_renders_no_section() -> None:
    """An empty or absent candidate_comparison emits no heading."""
    markdown = _markdown({"summary": "A synthesis with no comparison."})

    assert "Comparison of candidate ideas" not in markdown


def test_a_malformed_idea_entry_is_skipped_not_stringified() -> None:
    """A non-dict entry never leaks a raw Python repr into the report."""
    markdown = _markdown({"candidate_comparison": {"ideas": ["not a dict"]}})

    assert "not a dict" not in markdown


def test_an_idea_with_no_label_is_skipped() -> None:
    """A row missing its 'idea' label carries nothing to anchor it to."""
    markdown = _markdown(
        {
            "candidate_comparison": {
                "ideas": [{"distinguishing_attribute": "orphaned"}]
            }
        }
    )

    assert "orphaned" not in markdown
