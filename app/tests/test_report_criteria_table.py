"""R14-9: the ranking document renders criteria as a Criterion/Importance table.

The published protein-assemblies ranking report
(``references/core/google-co-scientist/research/supplements/ai-guided-
discovery-of-atypical-protein-assemblies/reports/top-ranking-
hypotheses.md:9-22``) renders its synthesized evaluation criteria as a
two-column GitHub-flavored markdown table, ``| Criterion | Importance |``,
distinct from the bolded-name-plus-prose form the Research Overview
document uses (matching MASH's own single combined report instead --
``_render_evaluation_criteria_markdown``, pinned by
``test_report_critical_criteria.py``). "Importance" is the same
``critical_criteria[].description`` field the prose renderer already
reads, under the published column label -- not a second synthesized
value.
"""

import re

from app import report_markdown


def _markdown(critical_criteria: list[object] | None) -> str:
    """Render a minimal ranking document carrying only the given criteria."""
    hypothesis: dict[str, object] = {
        "id": "h1",
        "title": "NHE1 coupling",
        "statement": "NHE1 couples to the RSK axis in HFpEF.",
    }
    return report_markdown.render_ranking_document_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[hypothesis],
            critical_criteria=critical_criteria,
        )
    )


def test_criteria_render_as_a_two_column_table() -> None:
    """Each criterion becomes one table row, not a bulleted paragraph."""
    markdown = _markdown(
        [
            {
                "name": "Quantitative Extractability",
                "description": (
                    "Parameters must be extractable from AF3 or PDB"
                    " coordinates using automated scripts."
                ),
            },
            {
                "name": "Mechanistic Grounding",
                "description": "Metrics must correlate with known functions.",
            },
        ]
    )

    assert "## Evaluation Criteria" in markdown
    assert "| Criterion | Importance |" in markdown
    assert "|---|---|" in markdown
    assert (
        "| Quantitative Extractability | Parameters must be extractable"
        " from AF3 or PDB coordinates using automated scripts. |"
    ) in markdown
    assert (
        "| Mechanistic Grounding | Metrics must correlate with known"
        " functions. |"
    ) in markdown
    # The prose form belongs to the Research Overview document only.
    assert "**Quantitative Extractability:**" not in markdown


def test_a_literal_pipe_in_a_cell_is_escaped() -> None:
    """A ``|`` inside a name or description cannot break the table shape."""
    markdown = _markdown(
        [
            {
                "name": "Sensitivity | Specificity",
                "description": "Balances true | false positive rates.",
            }
        ]
    )

    assert (
        "| Sensitivity \\| Specificity | Balances true \\| false positive"
        " rates. |"
    ) in markdown
    # No unescaped pipe splits either cell into extra columns -- exactly
    # the row's own three column delimiters remain unescaped.
    for line in markdown.splitlines():
        if line.startswith("| Sensitivity"):
            unescaped = re.findall(r"(?<!\\)\|", line)
            assert len(unescaped) == 3


def test_a_criterion_with_no_description_still_renders_its_row() -> None:
    """Degrade, never drop -- an empty second cell, not a missing row."""
    markdown = _markdown([{"name": "Statistical Robustness"}])

    assert "| Statistical Robustness |  |" in markdown


def test_no_usable_criteria_renders_no_table() -> None:
    """No entries at all -- no bare heading over an empty table."""
    markdown = _markdown(None)

    assert "Evaluation Criteria" not in markdown
    assert "| Criterion | Importance |" not in markdown


def test_the_table_sits_before_candidate_ideas() -> None:
    """Matches the published order: goal, criteria, then candidate ideas."""
    markdown = _markdown([{"name": "Statistical Robustness"}])

    assert markdown.index("| Criterion | Importance |") < markdown.index(
        "## Top hypotheses"
    )
