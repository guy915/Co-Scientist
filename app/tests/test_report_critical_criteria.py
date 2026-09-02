"""R12-18: the report renders the Supervisor's synthesized evaluation criteria.

The published MASH plan carries a "## **2. Evaluation Criteria**" section:
goal-specific criteria synthesized for that run, with names like "Kinetic
Feasibility and Experimental Readouts" and "Human Data Integration and
Accuracy" (``docs/CORPUS-EXTRACTION.md``, MASH body). The Supervisor
already synthesizes this list as ``workflow_plan.review_phase.
critical_criteria`` and ``prompts/review.py`` already injects it into
every reviewer prompt as "Critical Criteria to Emphasize" -- but nothing
ever rendered it to the reader. This pins that the markdown export now
does, under a heading distinct from the run's user-authored "Criteria"
bullet list under "Research Goal Details" (a different, plain-string field
from ``run_modes.DEFAULT_CRITERIA`` or the user's own setup -- see the
``report_markdown`` module's vocabulary warning: "Criteria" names two
differently-shaped things, one user-authored and one model-synthesized,
and conflating them would present the model's synthesis as the user's
own setup).
"""

from typing import Any

from app import report_markdown


def _markdown(
    critical_criteria: list[Any] | None,
    setup: dict[str, object] | None = None,
) -> str:
    """Render a minimal report carrying only the given critical criteria."""
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
            critical_criteria=critical_criteria,
            setup=setup,
        )
    )


def test_criteria_render_as_a_bullet_list() -> None:
    """Each synthesized criterion prints as its own bullet."""
    markdown = _markdown(
        [
            "Kinetic Feasibility and Experimental Readouts",
            "Human Data Integration and Accuracy",
        ]
    )

    assert "## Evaluation Criteria" in markdown
    assert "Kinetic Feasibility and Experimental Readouts" in markdown
    assert "Human Data Integration and Accuracy" in markdown


def test_no_critical_criteria_renders_no_section() -> None:
    """An absent criteria list emits no heading, not an empty one."""
    assert "Evaluation Criteria" not in _markdown(None)
    assert "Evaluation Criteria" not in _markdown([])


def test_all_blank_criteria_render_no_section() -> None:
    """Entries that are blank strings contribute nothing renderable."""
    markdown = _markdown(["", "   "])

    assert "Evaluation Criteria" not in markdown


def test_criteria_render_from_the_structured_shape() -> None:
    """R12-23: the flat list still renders names from the richer shape.

    critical_criteria may carry {name, questions} entries; this section
    only extracts the name -- the questions belong to the separate
    'Review Summary' section.
    """
    markdown = _markdown(
        [
            {
                "name": "Kinetic Feasibility and Experimental Readouts",
                "questions": [
                    {"name": "Kinetic Competition", "question": "Q?"}
                ],
            },
            "Human Data Integration and Accuracy",
        ]
    )

    assert "## Evaluation Criteria" in markdown
    assert "Kinetic Feasibility and Experimental Readouts" in markdown
    assert "Human Data Integration and Accuracy" in markdown


def test_malformed_criteria_render_no_section() -> None:
    """A field that is not a list at all degrades to nothing, not a crash."""
    markdown = _markdown("not a list")  # type: ignore[arg-type]

    assert "Evaluation Criteria" not in markdown


def test_criteria_render_with_description() -> None:
    """R12-23b: a criterion carrying prose renders Google's own shape.

    docs/CORPUS-EXTRACTION.md line 2558's section is a bolded name, a
    colon, then a prose paragraph -- not a bare name bullet.
    """
    markdown = _markdown(
        [
            {
                "name": "Kinetic Feasibility and Experimental Readouts",
                "description": (
                    "The experimental design must align with the"
                    " biological timeframe of the proposed mechanism."
                ),
            }
        ]
    )

    assert "## Evaluation Criteria" in markdown
    assert (
        "**Kinetic Feasibility and Experimental Readouts:** The"
        " experimental design must align with the biological timeframe"
        " of the proposed mechanism." in markdown
    )
    assert "- Kinetic Feasibility and Experimental Readouts" not in markdown


def test_criteria_without_description_falls_back_to_bullet() -> None:
    """A {name, questions} entry with no description degrades to a bullet.

    Covers both a legacy pre-R12-23b dict and a live run whose answer
    omitted description under the json_object downgrade -- degrade,
    never drop, never crash.
    """
    markdown = _markdown(
        [
            {
                "name": "Human Data Integration and Accuracy",
                "questions": [{"name": "Dataset Grounding", "question": "Q?"}],
            }
        ]
    )

    assert "## Evaluation Criteria" in markdown
    assert "- Human Data Integration and Accuracy" in markdown
    assert "**Human Data Integration and Accuracy:**" not in markdown


def test_blank_description_falls_back_to_bullet() -> None:
    """A whitespace-only description is treated as absent, not rendered."""
    markdown = _markdown(
        [{"name": "Safety and Therapeutic Viability", "description": "   "}]
    )

    assert "- Safety and Therapeutic Viability" in markdown
    assert "**Safety and Therapeutic Viability:**" not in markdown


def test_mixed_shapes_each_render_in_their_own_form() -> None:
    """A run mixing the description shape with legacy entries renders both."""
    markdown = _markdown(
        [
            {
                "name": "Biological Scope Alignment",
                "description": (
                    "Must reside within the designated focus areas."
                ),
            },
            "Mechanistic Novelty and Rigor in Fibrosis Reversal",
        ]
    )

    assert (
        "**Biological Scope Alignment:** Must reside within the"
        " designated focus areas." in markdown
    )
    assert "- Mechanistic Novelty and Rigor in Fibrosis Reversal" in markdown


def test_non_str_non_dict_entries_are_skipped_alongside_valid_ones() -> None:
    """An int/None/list entry contributes nothing; valid ones still render."""
    markdown = _markdown(
        [
            42,
            None,
            ["not", "a", "criterion"],
            {"name": "Valid Criterion", "description": "Valid prose."},
        ]
    )

    assert "**Valid Criterion:** Valid prose." in markdown


def test_distinct_from_the_user_authored_criteria_list() -> None:
    """The synthesized section never replaces the user-authored list.

    It coexists with the user-authored "Criteria" bullet list rendered
    under "Research Goal Details" -- same English word, two different
    published sections, see the module docstring's vocabulary warning.
    """
    markdown = _markdown(
        ["Mechanistic Novelty and Rigor in Fibrosis Reversal"],
        setup={"criteria": ["should be testable within two years"]},
    )

    assert "## Evaluation Criteria" in markdown
    assert "Mechanistic Novelty and Rigor in Fibrosis Reversal" in markdown
    assert "**Criteria:**" in markdown
    assert "should be testable within two years" in markdown
