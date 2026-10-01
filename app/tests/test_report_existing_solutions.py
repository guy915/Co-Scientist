"""R12-9: candidate ideas render against a comparison to existing solutions.

The MASH Goal Report's ``7 Comparison to Existing Solutions``
(``docs/CORPUS-EXTRACTION.md`` R12-9) frames current standard-of-care
practice against the run's proposed approaches. The table's columns follow
the run's own subject matter (``axes``, chosen per run) rather than a fixed
vocabulary -- see ``test_a_populated_comparison_renders_domain_aware_axes``
below. ``test_a_populated_comparison_renders_summary_and_row_columns`` pins
the older fixed-field shape a run's meta-review carried before that (still
accepted on read, per the renderer's own fallback). This whole section is
also expected to render nothing for a goal with no standard-of-care
landscape to compare against -- see
``test_no_existing_solutions_comparison_renders_no_section``.
"""

from app.report import markdown as report_markdown


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


def test_a_populated_comparison_renders_summary_and_row_columns() -> None:
    """The legacy fixed-field shape: a run's meta-review predating axes."""
    markdown = _markdown(
        {
            "existing_solutions_comparison": {
                "summary": (
                    "Current care slows progression rather than reversing it."
                ),
                "rows": [
                    {
                        "method": "Beta-blockade (standard of care)",
                        "approach": "Reduce afterload pharmacologically.",
                        "sensitivity_to_novelty": (
                            "Does not address the RSK-NHE1 axis."
                        ),
                        "scalability": "Widely available, low cost.",
                    }
                ],
            }
        }
    )

    assert "### Comparison to existing solutions" in markdown
    assert (
        "Current care slows progression rather than reversing it." in markdown
    )
    assert "Beta-blockade (standard of care)" in markdown
    assert "Reduce afterload pharmacologically." in markdown
    assert "Does not address the RSK-NHE1 axis." in markdown
    assert "Widely available, low cost." in markdown


def test_a_populated_comparison_renders_domain_aware_axes() -> None:
    """The current shape: per-run axes, rated positionally per row."""
    markdown = _markdown(
        {
            "existing_solutions_comparison": {
                "summary": (
                    "Current care slows progression rather than reversing it."
                ),
                "axes": ["Mechanism targeted", "Availability"],
                "rows": [
                    {
                        "method": "Beta-blockade (standard of care)",
                        "values": [
                            "Afterload, not the RSK-NHE1 axis.",
                            "Widely available, low cost.",
                        ],
                    }
                ],
            }
        }
    )

    assert "### Comparison to existing solutions" in markdown
    assert "Beta-blockade (standard of care)" in markdown
    assert (
        "**Mechanism targeted:** Afterload, not the RSK-NHE1 axis." in markdown
    )
    assert "**Availability:** Widely available, low cost." in markdown
    # Never the legacy fixed vocabulary alongside the domain-aware axes.
    assert "Sensitivity to novelty" not in markdown


def test_no_existing_solutions_comparison_renders_no_section() -> None:
    """An empty or absent existing_solutions_comparison emits no heading."""
    markdown = _markdown({"summary": "A synthesis with no comparison."})

    assert "Comparison to existing solutions" not in markdown


def test_a_malformed_row_entry_is_skipped_not_stringified() -> None:
    """A non-dict entry never leaks a raw Python repr into the report."""
    markdown = _markdown(
        {"existing_solutions_comparison": {"rows": ["not a dict"]}}
    )

    assert "not a dict" not in markdown


def test_a_row_with_no_method_is_skipped() -> None:
    """A row missing its 'method' label carries nothing to anchor it to."""
    markdown = _markdown(
        {"existing_solutions_comparison": {"rows": [{"approach": "orphaned"}]}}
    )

    assert "orphaned" not in markdown
