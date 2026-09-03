"""R14-27: the ranking document's own "Main Research Directions" section.

Google's published ranking report carries a narrative synthesis distinct
from any itemized directions array -- two prose paragraphs weaving the
run's directions together (``.../ai-guided-discovery-of-atypical-protein-
assemblies/reports/top-ranking-hypotheses.md:24-28``), sitting between the
Evaluation Criteria table and Candidate Ideas. This pins that
``meta_review.main_research_directions`` renders there, in that position,
and skips cleanly (no bare heading) when absent -- a legacy run persisted
before this field existed, or a provider that omits it under json_object
mode.
"""

from app import report_markdown


def _markdown(meta_review: dict[str, object] | None) -> str:
    """Render a minimal ranking document carrying only the given meta_review."""
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
            critical_criteria=[{"name": "Statistical Robustness"}],
            meta_review=meta_review,
        )
    )


def test_renders_the_two_paragraph_narrative() -> None:
    """The heading and both authored paragraphs appear verbatim."""
    markdown = _markdown(
        {
            "main_research_directions": (
                "One direction is **Metabolic State as an Intervention"
                " Point**, which matters because it is directly"
                " actionable.\n\n"
                "A second is **MazEF-State Biomarking**. Unexpectedly,"
                " both threads may track one underlying program."
            )
        }
    )

    assert "## Main Research Directions" in markdown
    assert (
        "One direction is **Metabolic State as an Intervention Point**,"
        " which matters because it is directly actionable."
    ) in markdown
    assert (
        "A second is **MazEF-State Biomarking**. Unexpectedly, both"
        " threads may track one underlying program."
    ) in markdown


def test_sits_after_criteria_table_and_before_candidate_ideas() -> None:
    """Matches the published order exactly."""
    markdown = _markdown(
        {"main_research_directions": "First paragraph.\n\nSecond paragraph."}
    )

    criteria_index = markdown.index("| Criterion | Importance |")
    directions_index = markdown.index("## Main Research Directions")
    candidates_index = markdown.index("## Top hypotheses")
    assert criteria_index < directions_index < candidates_index


def test_no_bare_heading_when_the_field_is_absent() -> None:
    """A legacy meta_review with no field at all renders no heading."""
    markdown = _markdown({"summary": "some other synthesis"})

    assert "Main Research Directions" not in markdown


def test_no_bare_heading_when_meta_review_is_none() -> None:
    """No meta_review at all (a run with no synthesis) renders no heading."""
    markdown = _markdown(None)

    assert "Main Research Directions" not in markdown


def test_no_bare_heading_when_the_field_is_blank() -> None:
    """An explicitly empty string degrades to nothing, not an empty heading."""
    markdown = _markdown({"main_research_directions": "   "})

    assert "Main Research Directions" not in markdown
