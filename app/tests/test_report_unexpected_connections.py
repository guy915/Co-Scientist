"""R12-7: the report surfaces the meta-review's cross-idea connections.

The MASH Goal Report carries an ``8 Key Findings and Unexpected Molecular
Connections`` section and a top-level ``Unexpected Connections`` section
(``docs/CORPUS-EXTRACTION.md`` R12-7). The engine already computes this --
``agents/meta_review/meta_review.py`` produces ``potential_connections`` and
``prompts/_common.py`` re-injects it into downstream prompts -- but
``_META_REVIEW_BULLET_SECTIONS`` never rendered it, so it was paid for and
discarded. Google's exemplar entries are not reproduced here: the published
four-field shape (Claims/Reasoning/Novelty/Relevance) has no analogue in our
schema, which computes ``related_hypotheses`` (short subject labels, e.g.
"Fluspirilene (Hypothesis 1)"), ``connection_type``, and
``synthesis_opportunity`` instead -- so this renders those real fields under
the published section name rather than inventing novelty/relevance verdicts
that were never judged.
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


def test_a_connection_renders_its_related_hypotheses_type_and_opportunity() -> (
    None
):
    """A structured connection entry prints all three of its real fields."""
    markdown = _markdown(
        {
            "potential_connections": [
                {
                    "related_hypotheses": [
                        "Fluspirilene (Hypothesis 1)",
                        "NHE1 blockade (Hypothesis 3)",
                    ],
                    "connection_type": "Shared calcium-handling mechanism",
                    "synthesis_opportunity": (
                        "Both ideas converge on mitochondrial calcium"
                        " uptake and could share a validation assay."
                    ),
                }
            ]
        }
    )

    assert "Unexpected connections" in markdown
    assert "Fluspirilene (Hypothesis 1)" in markdown
    assert "NHE1 blockade (Hypothesis 3)" in markdown
    assert "Shared calcium-handling mechanism" in markdown
    assert "share a validation assay" in markdown


def test_no_connections_renders_no_section() -> None:
    """An empty or absent potential_connections list emits no heading."""
    markdown = _markdown({"summary": "A synthesis with no cross-links."})

    assert "Unexpected connections" not in markdown


def test_a_malformed_connection_entry_is_skipped_not_stringified() -> None:
    """A non-dict entry never leaks a raw Python repr into the report."""
    markdown = _markdown({"potential_connections": ["not a dict"]})

    assert "not a dict" not in markdown
