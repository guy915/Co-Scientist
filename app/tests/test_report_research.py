from typing import Any

import pytest

from app.report.markdown.overview import render_research_overview_markdown
from tests._report_helpers import meta_review_markdown as _meta_review_markdown
from tests._report_helpers import render_markdown


def _overview_markdown(payload: dict[str, object]) -> str:
    return "\n".join(render_research_overview_markdown(payload))


def test_criteria_render_in_each_shape_beside_the_scientists_own() -> None:
    markdown = render_markdown(
        critical_criteria=[
            {
                "name": "Kinetic Feasibility",
                "description": "Design must match the biological timeframe.",
                "questions": [
                    {"name": "Kinetic Competition", "question": "Q?"}
                ],
            },
            {
                "name": "Human Data Integration",
                "questions": [{"name": "Dataset Grounding", "question": "Q?"}],
            },
            {"name": "Safety Viability", "description": "   "},
            "Mechanistic Novelty",
            42,
            None,
        ],
        setup={"criteria": ["should be testable within two years"]},
    )

    assert "## Evaluation Criteria" in markdown
    assert (
        "**Kinetic Feasibility:** Design must match the biological timeframe."
        in markdown
    )
    assert "- Human Data Integration" in markdown
    assert "- Safety Viability" in markdown
    assert "- Mechanistic Novelty" in markdown
    assert "**Human Data Integration:**" not in markdown
    assert "should be testable within two years" in markdown


@pytest.mark.parametrize("criteria", [None, [], ["", "   "], "not a list"])
def test_no_usable_criteria_renders_no_section(criteria: Any) -> None:
    assert "Evaluation Criteria" not in render_markdown(
        critical_criteria=criteria
    )


def test_main_research_directions_sit_immediately_before_top_hypotheses() -> (
    None
):
    markdown = render_markdown(
        meta_review={
            "main_research_directions": (
                "One direction is **Metabolic State**, which matters.\n\n"
                "A second is **MazEF-State Biomarking**. Unexpectedly, both "
                "may track one program."
            )
        }
    )

    assert "One direction is **Metabolic State**, which matters." in markdown
    assert "A second is **MazEF-State Biomarking**." in markdown
    assert markdown.index("## Main Research Directions") < markdown.index(
        "## Top hypotheses"
    )


@pytest.mark.parametrize(
    "meta_review",
    [None, {"summary": "other"}, {"main_research_directions": "   "}],
)
def test_no_bare_main_research_directions_heading(
    meta_review: dict[str, object] | None,
) -> None:
    assert "Main Research Directions" not in render_markdown(
        meta_review=meta_review
    )


def test_themes_render_with_sub_themes_and_older_flat_shapes() -> None:
    markdown = _meta_review_markdown(
        {
            "recurring_themes": [
                {
                    "theme": "Core Hypothesis",
                    "description": "How the mechanism is argued.",
                    "frequency": "very common",
                    "sub_themes": [
                        {
                            "theme": "Driver vs. Consequence",
                            "description": "Whether it initiates or follows.",
                            "points": ["Show the temporal sequence."],
                        },
                        {
                            "theme": "Incremental vs. Groundbreaking",
                            "description": "Builds on existing knowledge.",
                            "points": [],
                        },
                        "State every assumption explicitly.",
                    ],
                },
                {
                    "theme": "Motor neuron specificity",
                    "description": "Rarely explained.",
                    "frequency": "common",
                },
                {"theme": "", "description": "orphaned text", "frequency": ""},
            ],
        }
    )
    bare = _meta_review_markdown(
        {"emerging_themes": ["Time-resolved state measurements"]}
    )

    assert "### Emerging themes" in markdown
    assert "#### Core Hypothesis" in markdown
    assert "- **Driver vs. Consequence**: Whether it initiates" in markdown
    assert "  - Show the temporal sequence." in markdown
    assert "- **Incremental vs. Groundbreaking**: Builds on" in markdown
    assert "- State every assumption explicitly." in markdown
    assert "#### Motor neuron specificity" in markdown
    assert "Rarely explained." in markdown
    assert "- Time-resolved state measurements" in bare
    assert "orphaned text" not in markdown
    assert "****:" not in markdown


def test_open_questions_and_patterns_render_and_flatten_json() -> None:
    markdown = _overview_markdown(
        {
            "open_questions": [
                "To what extent can X be targeted to reverse Y?",
                '{"question": "What drives X?"}',
            ],
            "clear_patterns": ["Lipid handling recurs across every idea."],
            "unexpected_patterns": ["A metabolic block explains a failure."],
        }
    )

    assert "## Open questions" in markdown
    assert "1. To what extent can X be targeted to reverse Y?" in markdown
    assert "2. What drives X?" in markdown
    assert '{"question"' not in markdown
    assert "### Clear patterns" in markdown
    assert "Lipid handling recurs across every idea." in markdown
    assert "### Unexpected patterns" in markdown
    assert "A metabolic block explains a failure." in markdown


def test_no_open_questions_or_patterns_renders_no_section() -> None:
    markdown = _overview_markdown({"overview": {"summary": "S"}})

    for heading in ("Open questions", "Clear patterns", "Unexpected patterns"):
        assert heading not in markdown


def test_recommendations_render_as_a_primary_step_and_a_numbered_roadmap() -> (
    None
):
    markdown = _meta_review_markdown(
        {
            "strategic_recommendations": [
                {
                    "focus_area": "Calcium handling",
                    "recommendation": "Measure MCU flux directly.",
                    "justification": "The current data is indirect.",
                    "time_estimate": "Weeks 1-2",
                    "recommended_idea": "Hypothesis 1, building on 4",
                },
                {
                    "focus_area": "Validation",
                    "recommendation": "Confirm the mechanism in vivo.",
                    "phase_label": "Phase A",
                },
                "A bare-string recommendation.",
            ]
        }
    )

    assert "### Recommendation and strategic roadmap" in markdown
    assert "### Strategic recommendations" not in markdown
    assert (
        "**Primary recommendation:** **Calcium handling**: Measure MCU"
        " flux directly. (Weeks 1-2)" in markdown
    )
    assert "The current data is indirect." in markdown
    assert "Recommended idea: Hypothesis 1, building on 4" in markdown
    assert (
        "1. Phase A: **Validation**: Confirm the mechanism in vivo." in markdown
    )
    assert "2. A bare-string recommendation." in markdown


def test_a_single_recommendation_has_no_roadmap_and_none_has_no_section() -> (
    None
):
    single = _meta_review_markdown(
        {"strategic_recommendations": ["Only one recommendation."]}
    )
    none = _meta_review_markdown({"summary": "Nothing to recommend yet."})

    assert "**Primary recommendation:** Only one recommendation." in single
    assert (
        "1." not in single.split("### Recommendation and strategic roadmap")[1]
    )
    assert "Recommendation and strategic roadmap" not in none


def test_attributes_render_as_named_scales_beside_the_scientists_own() -> None:
    markdown = render_markdown(
        attributes=[
            {
                "name": "Mechanism Novelty",
                "rubric": "1: Established, 5: Highly novel.",
            },
            {"rubric": "orphaned rubric text"},
        ],
        setup={"attributes": ["Should be testable in human tissue"]},
    )

    assert "## Stratification Attributes" in markdown
    assert "Mechanism Novelty" in markdown
    assert "5: Highly novel." in markdown
    assert "orphaned rubric text" not in markdown
    assert "Should be testable in human tissue" in markdown


@pytest.mark.parametrize(
    "attributes", [None, [], [{"rubric": "orphaned rubric text"}]]
)
def test_no_usable_attributes_renders_no_section(
    attributes: list[dict[str, object]] | None,
) -> None:
    assert "Stratification Attributes" not in render_markdown(
        attributes=attributes
    )


def test_a_connection_renders_its_related_hypotheses_type_and_opportunity() -> (
    None
):
    markdown = _meta_review_markdown(
        {
            "potential_connections": [
                {
                    "related_hypotheses": [
                        "Fluspirilene (Hypothesis 1)",
                        "NHE1 blockade (Hypothesis 3)",
                    ],
                    "connection_type": "Shared calcium-handling mechanism",
                    "synthesis_opportunity": "Could share a validation assay.",
                },
                "not a dict",
            ]
        }
    )

    assert "Unexpected connections" in markdown
    assert "Fluspirilene (Hypothesis 1)" in markdown
    assert "NHE1 blockade (Hypothesis 3)" in markdown
    assert "Shared calcium-handling mechanism" in markdown
    assert "share a validation assay" in markdown
    assert "not a dict" not in markdown


def test_no_connections_renders_no_section() -> None:
    markdown = _meta_review_markdown({"summary": "No cross-links."})

    assert "Unexpected connections" not in markdown


def test_unexpected_directions_render_after_the_directions_they_extend() -> (
    None
):
    markdown = _overview_markdown(
        {
            "overview": {
                "summary": "S",
                "research_directions": [{"title": "A", "importance": "I"}],
            },
            "unexpected_research_directions": [
                {
                    "title": "Nuclear LOXL2",
                    "description": "May act as a histone aminooxidase.",
                },
                {"title": "Bare title"},
                {"title": "X", "description": '{"claim": "worth pursuing"}'},
            ],
        }
    )

    assert (
        markdown.index("## Research Overview")
        < markdown.index("### A")
        < markdown.index("### Unexpected research directions")
    )
    assert "- **Nuclear LOXL2:** May act as a histone aminooxidase." in markdown
    assert "- Bare title" in markdown
    assert "- **Bare title:**" not in markdown
    assert "worth pursuing" in markdown
    assert '{"claim"' not in markdown


def test_no_unexpected_directions_renders_no_heading() -> None:
    markdown = _overview_markdown(
        {"overview": {"summary": "S", "research_directions": []}}
    )

    assert "Unexpected research directions" not in markdown
