"""R12-6: the report renders the run's Knowledge Base.

The MASH Goal Report carries a ``Knowledge Base`` section wrapping a
``Knowledge Summary`` of named subject headings, each holding dense prose
-- and, notably, zero citations anywhere in the span
(``docs/CORPUS-EXTRACTION.md`` R12-6). ``report_content._knowledge_base_topics``
/ ``_synthesized_knowledge_base_topics`` already compute this, and it is
persisted into the payload and rendered in the React UI, but the markdown
renderer never emitted it -- computed, paid for, and dropped on this one
surface only. This pins that the section now renders, and that it carries
no reference/citation apparatus, matching the published exemplar.
"""

from app import report_markdown


def _markdown(knowledge_base: list[dict[str, object]]) -> str:
    """Render a minimal report carrying only the given knowledge base."""
    hypothesis: dict[str, object] = {
        "id": "h1",
        "title": "NHE1 coupling",
        "statement": "NHE1 couples to the RSK axis in HFpEF.",
    }
    return report_markdown.render_overview_document_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[hypothesis],
            knowledge_base=knowledge_base,
        )
    )


def test_a_topic_renders_its_title_summary_and_detail() -> None:
    """Each topic prints as a named subject heading with its prose."""
    markdown = _markdown(
        [
            {
                "id": "topic-1",
                "title": "Mitochondrial calcium handling",
                "summary": "Calcium influx couples to ROS production.",
                "detail": (
                    "Perturbing MCU activity shifts the balance toward"
                    " sustained oxidative stress in motor neurons."
                ),
                "reference_ids": ["ev-1", "ev-2"],
            }
        ]
    )

    assert "## Knowledge Base" in markdown
    assert "### Knowledge Summary" in markdown
    assert "Mitochondrial calcium handling" in markdown
    assert "Calcium influx couples to ROS production." in markdown
    assert "Perturbing MCU activity shifts the balance" in markdown


def test_the_section_carries_no_citation_apparatus() -> None:
    """Reference ids attached to a topic never surface as markdown output.

    Verified over the whole published span (R12-6): the Knowledge Base
    carries zero citations, unlike every other numbered report section.
    """
    markdown = _markdown(
        [
            {
                "id": "topic-1",
                "title": "Autophagy dysfunction",
                "summary": "Autophagosome clearance is delayed.",
                "detail": "See the retrieved literature for detail.",
                "reference_ids": ["ev-42"],
            }
        ]
    )

    section = markdown.split("## Knowledge Base")[1]
    assert "ev-42" not in section
    assert "[" not in section.split("### Knowledge Summary")[1]


def test_no_topics_renders_no_section() -> None:
    """An empty knowledge base emits no heading at all."""
    markdown = _markdown([])

    assert "Knowledge Base" not in markdown


def test_a_topic_with_no_title_is_skipped() -> None:
    """A malformed topic with no title contributes nothing renderable."""
    markdown = _markdown(
        [{"id": "topic-1", "summary": "orphaned prose", "detail": ""}]
    )

    assert "orphaned prose" not in markdown
