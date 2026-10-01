"""R12-23: the report renders the Supervisor's synthesized review rubric.

The published "Review summary" section (``docs/CORPUS-EXTRACTION.md``,
line 2929) is the rubric reviewers were given, not a verdict: 5 numbered
criteria, each with 3-4 named yes/no reviewer questions. The Supervisor
already synthesizes ``workflow_plan.review_phase.critical_criteria`` and
``prompts/review.py`` already injects it into every reviewer prompt; this
pins that the markdown export now renders it as its own "## Review
Summary" section, distinct from the flat "## Evaluation Criteria" list
(``test_report_critical_criteria.py``) that renders only the names.

Runs persisted before R12-23 carry ``critical_criteria`` as a bare list of
strings (no questions), and production's json_object downgrade means a
live run can answer with either shape -- both must render without
crashing, the legacy shape degrading to numbered names with no questions.
"""

from typing import Any

from app.report import markdown as report_markdown


def _markdown(critical_criteria: list[Any] | None) -> str:
    """Render a minimal report carrying only the given critical criteria."""
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
            critical_criteria=critical_criteria,
        )
    )


def test_renders_from_the_structured_shape() -> None:
    """Each criterion is a numbered heading with its named questions below."""
    markdown = _markdown(
        [
            {
                "name": "Kinetic Feasibility and Experimental Readouts",
                "questions": [
                    {
                        "name": "Biological Timeframe Consistency",
                        "question": (
                            "Does the design account for the mechanism's"
                            " kinetics?"
                        ),
                    },
                    {
                        "name": "Kinetic Competition",
                        "question": "Does degradation outpace synthesis?",
                    },
                ],
            },
            {
                "name": "Human Data Integration and Accuracy",
                "questions": [
                    {
                        "name": "Dataset Grounding",
                        "question": "Is the hypothesis grounded in human data?",
                    }
                ],
            },
        ]
    )

    assert "## Review Summary" in markdown
    assert "### 1. Kinetic Feasibility and Experimental Readouts" in markdown
    assert (
        "- **Biological Timeframe Consistency:** Does the design account"
        " for the mechanism's kinetics?" in markdown
    )
    assert "- **Kinetic Competition:** Does degradation outpace synthesis?" in (
        markdown
    )
    assert "### 2. Human Data Integration and Accuracy" in markdown
    assert (
        "- **Dataset Grounding:** Is the hypothesis grounded in human data?"
        in markdown
    )


def test_renders_from_the_legacy_string_list() -> None:
    """A pre-R12-23 bare-string list still renders, minus the questions."""
    markdown = _markdown(
        [
            "Kinetic Feasibility and Experimental Readouts",
            "Human Data Integration and Accuracy",
        ]
    )

    assert "## Review Summary" in markdown
    assert "### 1. Kinetic Feasibility and Experimental Readouts" in markdown
    assert "### 2. Human Data Integration and Accuracy" in markdown


def test_absent_criteria_renders_no_section() -> None:
    """No critical_criteria means no heading and no body."""
    assert "Review Summary" not in _markdown(None)
    assert "Review Summary" not in _markdown([])


def test_malformed_criteria_render_no_section() -> None:
    """A field of the wrong type degrades to nothing rather than raising."""
    assert "Review Summary" not in _markdown("not a list")  # type: ignore[arg-type]
    assert "Review Summary" not in _markdown([42, None, {"questions": []}])
    assert "Review Summary" not in _markdown([{"name": "   "}])


def test_malformed_entries_are_skipped_alongside_valid_ones() -> None:
    """A mixed list keeps the well-formed criteria, drops the rest."""
    markdown = _markdown(
        [
            {"name": "Valid Criterion", "questions": [{"question": "Q1?"}]},
            {"name": ""},
            42,
            None,
        ]
    )

    assert "## Review Summary" in markdown
    assert "### 1. Valid Criterion" in markdown
    assert "- Q1?" in markdown


def test_malformed_question_entries_are_skipped() -> None:
    """A criterion's own malformed question entries render no bullet."""
    markdown = _markdown(
        [
            {
                "name": "Valid Criterion",
                "questions": [
                    {"name": "Named", "question": "Named text?"},
                    {"question": ""},
                    "not a question object",
                    42,
                ],
            }
        ]
    )

    assert "- **Named:** Named text?" in markdown
    assert "not a question object" not in markdown
