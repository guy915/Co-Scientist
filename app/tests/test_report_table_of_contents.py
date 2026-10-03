"""R14-1: the report opens with a table of contents naming its sections.

Google's published ``research-overview.md`` opens with an explicit
``#### Table of contents:`` block, six bulleted nav items pointing at that
document's own sections (``docs/CORPUS-EXTRACTION.md`` R14-1). Our Goal
Report document renders a different, run-dependent set of top-level
sections, each independently conditional (R14-23) -- these pin that the
nav list always reflects what this particular render actually produced,
never a static mirror of Google's fixed six, and that it degrades safely
rather than mistaking a model-authored field's prose for one of the
report's own section headings.
"""

from typing import Any

from app.report import markdown as report_markdown
from app.report.markdown import document as report_markdown_toc


def _markdown(**overrides: Any) -> str:
    """Render the overview document, defaulting to one bare hypothesis."""
    hypothesis: dict[str, Any] = overrides.pop(
        "hypothesis",
        {
            "id": "h1",
            "title": "NHE1 coupling",
            "statement": "NHE1 couples to the RSK axis in HFpEF.",
        },
    )
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[hypothesis] if hypothesis else [],
            **overrides,
        )
    )


def test_table_of_contents_lists_only_the_sections_this_render_produced() -> (
    None
):
    """The nav list names exactly the populated sections, in document order.

    Deliberately does not match Google's six items: this run carries
    Stratification Attributes and Knowledge Base, which Google's exemplar
    does not, and omits several Google does carry (Open questions,
    Research Contacts) because this run has none.
    """
    markdown = _markdown(
        attributes=[{"name": "Human Relevance", "rubric": "1-5 scale."}],
        meta_review={"summary": "Ideas converge on a shared mechanism."},
        knowledge_base=[{"title": "NHE1", "summary": "Background."}],
    )

    lines = markdown.splitlines()
    toc_at = lines.index("#### Table of contents:")
    assert lines[toc_at + 1] == ""
    assert lines[toc_at + 2] == "- Stratification Attributes"
    assert lines[toc_at + 3] == "- Meta-review insights"
    assert lines[toc_at + 4] == "- Top hypotheses"
    assert lines[toc_at + 5] == "- Knowledge Base"
    # Sections this run never populated stay out of the nav list.
    assert "- Research Goal Details" not in markdown
    assert "- Open questions" not in markdown
    assert "- Research Contacts" not in markdown


def test_table_of_contents_opens_the_report_before_any_section() -> None:
    """The nav list sits right after the title/provider line, before body."""
    markdown = _markdown(
        meta_review={"summary": "Ideas converge on a shared mechanism."}
    )

    lines = markdown.splitlines()
    assert lines[0] == "# Research Report — Explain the cardiac benefit."
    toc_at = lines.index("#### Table of contents:")
    goal_at = markdown.find("## Research Goal Details")
    hypotheses_at = markdown.find("## Top hypotheses")
    # Right after the always-present title/provider line and the R14-4
    # About disclosure -- both unconditional, so this bound just excludes
    # any actual section content, not a fixed line count.
    assert toc_at < 8
    # No populated section renders ahead of the nav list.
    assert goal_at == -1
    assert markdown.index("#### Table of contents:") < hypotheses_at


def test_table_of_contents_still_lists_the_lone_populated_section() -> None:
    """A minimal report has one always-present section: the hypothesis list.

    "Top hypotheses", the full per-idea write-up, is the only section a
    run with nothing else populated ever produces.
    """
    markdown = _markdown()

    lines = markdown.splitlines()
    toc_at = lines.index("#### Table of contents:")
    assert lines[toc_at + 2] == "- Top hypotheses"
    assert lines[toc_at + 3] == ""


def test_table_of_contents_omitted_with_nothing_to_navigate() -> None:
    """Zero populated sections renders no nav block at all, not an empty one."""
    assert report_markdown_toc._render_table_of_contents([]) == []
    assert report_markdown_toc._render_table_of_contents([[], [], []]) == []


def test_table_of_contents_ignores_a_bogus_heading_inside_body_prose() -> None:
    """A model-authored field opening with '##' is not read as a section.

    Under the json_object downgrade nothing constrains an LLM-authored
    field's content -- a section could carry a body paragraph that itself
    starts with something that looks like a markdown heading. The table
    of contents must only scan the section's own leading line, exactly as
    ``_render_table_of_contents``'s docstring states, never a line buried
    later in that same section's body.
    """
    sections = [
        ["## Real heading", "", "some prose", "## Fake heading in the body"],
    ]

    toc = report_markdown_toc._render_table_of_contents(sections)

    assert toc == ["#### Table of contents:", "", "- Real heading", ""]
    assert "Fake heading" not in "\n".join(toc)


def test_table_of_contents_degrades_when_research_overview_is_malformed() -> (
    None
):
    """A non-dict research_overview contributes no phantom nav entries."""
    markdown = _markdown(research_overview="not a dict")

    lines = markdown.splitlines()
    toc_at = lines.index("#### Table of contents:")
    assert lines[toc_at + 2] == "- Top hypotheses"
    assert lines[toc_at + 3] == ""
