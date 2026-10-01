"""R12-11: strategic recommendations render as a staged roadmap.

The MASH Goal Report's ``9 Recommendation and Strategic Roadmap`` names a
primary recommendation, then sequences four named phases each with
concrete next steps (``docs/CORPUS-EXTRACTION.md`` R12-11). Our
``strategic_recommendations`` is a flat list of
``{focus_area, recommendation, justification}`` with no phase name,
dependency, or ordering field -- so named phases with assays would be
invented content the schema cannot support. This is a presentation
change only: the first recommendation is distinguished as the primary
one and the rest render as a numbered roadmap, matching what the data
actually carries.
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


def test_the_section_is_named_recommendation_and_strategic_roadmap() -> None:
    """The heading matches the published section title, not the old label."""
    markdown = _markdown(
        {
            "strategic_recommendations": [
                {
                    "focus_area": "Calcium handling",
                    "recommendation": "Measure MCU flux directly.",
                    "justification": "The current data is indirect.",
                }
            ]
        }
    )

    assert "### Recommendation and strategic roadmap" in markdown
    assert "### Strategic recommendations" not in markdown


def test_the_first_recommendation_is_distinguished_as_primary() -> None:
    """The lead entry is labelled primary, not folded into the roadmap list."""
    markdown = _markdown(
        {
            "strategic_recommendations": [
                {
                    "focus_area": "Calcium handling",
                    "recommendation": "Measure MCU flux directly.",
                    "justification": "The current data is indirect.",
                }
            ]
        }
    )

    assert "**Primary recommendation:**" in markdown
    assert "Measure MCU flux directly." in markdown
    assert "The current data is indirect." in markdown


def test_remaining_recommendations_render_as_a_numbered_roadmap() -> None:
    """Every recommendation after the first is a numbered roadmap step."""
    markdown = _markdown(
        {
            "strategic_recommendations": [
                {
                    "focus_area": "Calcium handling",
                    "recommendation": "Measure MCU flux directly.",
                },
                {
                    "focus_area": "Motor neuron specificity",
                    "recommendation": "Compare cell types under stress.",
                },
                "A bare-string recommendation.",
            ]
        }
    )

    assert "1. **Motor neuron specificity**" in markdown
    assert "2. A bare-string recommendation." in markdown


def test_a_single_recommendation_has_no_roadmap_steps() -> None:
    """One recommendation renders only the primary line, no numbering."""
    markdown = _markdown(
        {"strategic_recommendations": ["Only one recommendation."]}
    )

    assert "**Primary recommendation:** Only one recommendation." in markdown
    roadmap_section = markdown.split(
        "### Recommendation and strategic roadmap"
    )[1]
    assert "1." not in roadmap_section


def test_no_recommendations_renders_no_section() -> None:
    """An empty list emits no heading at all."""
    markdown = _markdown({"summary": "Nothing to recommend yet."})

    assert "Recommendation and strategic roadmap" not in markdown


def test_time_estimate_renders_as_a_parenthetical_suffix() -> None:
    """R14-8: a step's timeline appends after its recommendation text."""
    markdown = _markdown(
        {
            "strategic_recommendations": [
                {
                    "focus_area": "Calcium handling",
                    "recommendation": "Measure MCU flux directly.",
                    "time_estimate": "Weeks 1-2",
                }
            ]
        }
    )

    assert (
        "**Primary recommendation:** **Calcium handling**: Measure MCU"
        " flux directly. (Weeks 1-2)" in markdown
    )


def test_phase_label_prefixes_the_step() -> None:
    """R14-8: a lettered sub-phase prefixes the step's own text."""
    markdown = _markdown(
        {
            "strategic_recommendations": [
                {"recommendation": "Lead step."},
                {
                    "focus_area": "Validation",
                    "recommendation": "Confirm the mechanism in vivo.",
                    "phase_label": "Phase A",
                },
            ]
        }
    )

    assert (
        "1. Phase A: **Validation**: Confirm the mechanism in vivo." in markdown
    )


def test_recommended_idea_renders_its_own_line() -> None:
    """R14-8: the named-idea selection, identified by number, not text."""
    markdown = _markdown(
        {
            "strategic_recommendations": [
                {
                    "recommendation": "Proceed with the lead candidate.",
                    "recommended_idea": (
                        "Hypothesis 1, building on Hypothesis 4"
                    ),
                }
            ]
        }
    )

    assert (
        "Recommended idea: Hypothesis 1, building on Hypothesis 4" in markdown
    )


def test_a_report_with_none_of_the_new_fields_is_unaffected() -> None:
    """A report persisted before R14-8 renders exactly as it did."""
    markdown = _markdown(
        {
            "strategic_recommendations": [
                {
                    "focus_area": "Calcium handling",
                    "recommendation": "Measure MCU flux directly.",
                    "justification": "The current data is indirect.",
                }
            ]
        }
    )

    assert "Weeks" not in markdown
    assert "Phase" not in markdown
    assert "Recommended idea" not in markdown
