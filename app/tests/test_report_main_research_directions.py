"""R14-27: the report's own "Main Research Directions" section.

Google's published ranking report carries a narrative synthesis distinct
from any itemized directions array -- two prose paragraphs weaving the
run's directions together (``.../ai-guided-discovery-of-atypical-protein-
assemblies/reports/top-ranking-hypotheses.md:24-28``), sitting immediately
before Candidate Ideas -- this repo's Top hypotheses section. This pins
that ``meta_review.main_research_directions`` renders there, in that
position, and skips cleanly (no bare heading) when absent -- a legacy run
persisted before this field existed, or a provider that omits it under
json_object mode.
"""

from app.report import markdown as report_markdown


def _markdown(meta_review: dict[str, object] | None) -> str:
    """Render a minimal report carrying only the given meta_review."""
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


def test_sits_immediately_before_top_hypotheses() -> None:
    """Matches the published "before Candidate Ideas" placement."""
    markdown = _markdown(
        {"main_research_directions": "First paragraph.\n\nSecond paragraph."}
    )

    directions_index = markdown.index("## Main Research Directions")
    candidates_index = markdown.index("## Top hypotheses")
    assert directions_index < candidates_index


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
