"""R12-8: the report header carries the run's own configuration.

The MASH Goal Report opens with a ``Research Goal Details`` block --
Goal / Requirements / Attributes / Criteria -- before any hypothesis
content (``docs/CORPUS-EXTRACTION.md`` R12-8, MASH report L3-40). Our
header rendered only the title, a provider line, and an optional summary;
requirements, attributes, and criteria are collected by
``run_modes.setup_config`` into the run's persisted ``setup`` block but
were never rendered. This pins that the header now surfaces them.
"""

from app.report import markdown as report_markdown


def _markdown(setup: dict[str, object] | None) -> str:
    """Render a minimal report carrying only the given setup block."""
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[],
            setup=setup,
        )
    )


def test_the_header_carries_goal_requirements_attributes_and_criteria() -> None:
    """Every configured section of the run's plan renders."""
    markdown = _markdown(
        {
            "goal": "Explain the cardiac benefit.",
            "requirements": ["Must be testable in vitro."],
            "attributes": ["Mechanistically specific"],
            "criteria": ["Scientific soundness"],
        }
    )

    assert "## Research Goal Details" in markdown
    assert "**Goal:** Explain the cardiac benefit." in markdown
    assert "**Requirements:**" in markdown
    assert "Must be testable in vitro." in markdown
    assert "**Attributes:**" in markdown
    assert "Mechanistically specific" in markdown
    assert "**Criteria:**" in markdown
    assert "Scientific soundness" in markdown


def test_the_header_renders_r12_4_name_value_criteria() -> None:
    """A run created after R12-4 stores criteria as name/value pairs."""
    markdown = _markdown(
        {
            "goal": "Explain the cardiac benefit.",
            "criteria": [{"name": "Idea correctness", "value": "Required"}],
        }
    )

    assert "**Criteria:**" in markdown
    assert "- Idea correctness: Required" in markdown


def test_the_header_renders_r12_5_structured_attributes() -> None:
    """A run created after R12-5 stores attributes as structured axes."""
    markdown = _markdown(
        {
            "goal": "Explain the cardiac benefit.",
            "attributes": [
                {
                    "name": "Mechanism Novelty",
                    "scale": {"1": "Low", "3": "Moderate", "5": "High"},
                },
                {"name": "Target Area", "values": ["Heart", "Vasculature"]},
            ],
        }
    )

    assert "**Attributes:**" in markdown
    assert (
        "- Mechanism Novelty: 1-5 scale (1: Low, 3: Moderate, 5: High)"
        in markdown
    )
    assert "- Target Area (Heart or Vasculature)" in markdown


def test_the_header_still_leads_with_the_title_and_provider() -> None:
    """The new section is additive: title and provider line still open."""
    markdown = _markdown({"requirements": ["A requirement."]})

    lines = markdown.splitlines()
    assert lines[0] == "# Research Report — Explain the cardiac benefit."
    assert "_Provider: **engine**_" in markdown


def test_no_setup_block_renders_no_goal_details_section() -> None:
    """A report built without a setup block (an old persisted run) is fine."""
    markdown = _markdown(None)

    assert "Research Goal Details" not in markdown


def test_an_empty_setup_block_renders_no_goal_details_section() -> None:
    """A setup block with nothing configured emits no bare heading."""
    markdown = _markdown({"requirements": [], "attributes": [], "criteria": []})

    assert "Research Goal Details" not in markdown
