"""R12-6: the report renders the run's Knowledge Base.

The MASH Goal Report carries a ``Knowledge Base`` section as a two-level
heading hierarchy -- named themes, each wrapping the named subject
headings that hold the dense prose -- and, notably, zero citations
anywhere in the span (``docs/CORPUS-EXTRACTION.md`` R12-6).
``report_content._knowledge_base_topics`` / ``_synthesized_knowledge_base_
topics`` already compute this, and it is persisted into the payload and
rendered in the React UI, but the markdown renderer never emitted it --
computed, paid for, and dropped on this one surface only. This pins that
the section now renders as ``## Knowledge Base`` / ``### <theme>`` /
``#### <subject>``, that a themed topic's ``### <theme>`` heading uses
the theme's own name, that the flat fallback shape (a topic carrying no
theme) falls under ``### Knowledge Summary`` instead, and that the span
carries no reference/citation apparatus, matching the published
exemplar.
"""

from app import report_markdown


def _markdown(knowledge_base: list[dict[str, object]]) -> str:
    """Render a minimal report carrying only the given knowledge base."""
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


# F8: the published Knowledge Base groups its named subject headings under
# themes ("Extracellular Matrix Architecture And Biomechanical Barriers"
# over "Matrix Composition And Cross-Linking Constraints", ...). The engine
# synthesizes those as one topic per section carrying its theme; the
# renderer prints each theme once, as a heading one level above the
# sections that belong to it, exactly as the exemplar does.
#
# Production run d1273490 is why these assert on heading level rather than
# on the theme text appearing at all: the deep call answered with 8 themes
# over 38 grounded sections, and the renderer emitted every theme as a
# **bold paragraph** under one static "### Knowledge Summary". The depth
# landed and the taxonomy did not -- in an outline, a table of contents or
# any heading-based view the whole section read as a single theme, and the
# earlier test passed because it asserted the bold form.


def _themed(theme: str, title: str, detail: str) -> dict[str, object]:
    """One themed knowledge-base section as the engine emits it."""
    return {
        "id": f"topic-{title}",
        "theme": theme,
        "title": title,
        "summary": "",
        "detail": detail,
        "uncertainty": "",
        "reference_ids": ["ev-1"],
    }


def test_a_theme_is_printed_once_above_its_sections() -> None:
    """Consecutive sections of one theme share a single theme heading."""
    markdown = _markdown(
        [
            _themed("Matrix Architecture", "Cross-Linking", "Dense prose."),
            _themed("Matrix Architecture", "Stiffness", "More prose."),
            _themed("Immune Niche", "Macrophages", "Other prose."),
        ]
    )

    section = markdown.split("## Knowledge Base")[1]
    assert section.count("### Matrix Architecture") == 1
    assert section.count("### Immune Niche") == 1
    assert "#### Cross-Linking" in section
    assert "#### Stiffness" in section
    assert "#### Macrophages" in section
    assert "**" not in section


def test_every_theme_reaches_the_reader_as_its_own_heading() -> None:
    """A run's whole taxonomy renders as headings, not as one section.

    The shape production run d1273490 actually produced: the maximum 8
    themes, several sections each. Every theme must be its own ``###``,
    and the flat path's label must not appear at all.
    """
    themes = [f"Theme {index}" for index in range(1, 9)]
    markdown = _markdown(
        [
            _themed(theme, f"{theme} section {number}", "Dense prose.")
            for theme in themes
            for number in (1, 2, 3)
        ]
    )

    section = markdown.split("## Knowledge Base")[1]
    assert [
        line for line in section.splitlines() if line.startswith("### ")
    ] == [f"### {theme}" for theme in themes]
    assert section.count("#### ") == 24
    assert "### Knowledge Summary" not in section


def test_a_single_theme_still_renders_as_that_theme() -> None:
    """One theme is a legitimate answer, not the degraded shape."""
    markdown = _markdown(
        [
            _themed("Matrix Architecture", "Cross-Linking", "Dense prose."),
            _themed("Matrix Architecture", "Stiffness", "More prose."),
        ]
    )

    section = markdown.split("## Knowledge Base")[1]
    assert section.count("### Matrix Architecture") == 1
    assert "Knowledge Summary" not in section


def test_an_unthemed_topic_never_inherits_the_previous_theme() -> None:
    """A topic with no theme falls under the flat label, not a theme."""
    markdown = _markdown(
        [
            _themed("Matrix Architecture", "Cross-Linking", "Dense prose."),
            {
                "id": "topic-flat",
                "title": "Autophagy dysfunction",
                "summary": "",
                "detail": "Detail prose.",
                "uncertainty": "",
            },
        ]
    )

    section = markdown.split("## Knowledge Base")[1]
    assert "### Knowledge Summary\n\n#### Autophagy dysfunction" in section


def test_untheme_d_topics_render_exactly_as_before() -> None:
    """The flat shape the overview call still produces is unchanged."""
    markdown = _markdown(
        [
            {
                "id": "topic-1",
                "title": "Autophagy dysfunction",
                "summary": "Clearance is delayed.",
                "detail": "Detail prose.",
                "reference_ids": [],
            }
        ]
    )

    section = markdown.split("## Knowledge Base")[1]
    assert "### Knowledge Summary" in section
    assert "#### Autophagy dysfunction" in section
    assert "**" not in section
