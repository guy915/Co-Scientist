"""critical_criteria's richer {name, questions} shape, and its legacy form.

R12-23: workflow_plan.review_phase.critical_criteria moved from a bare
list of criterion-name strings to a list of {name, questions[]} objects,
each question itself {name, question} -- mirroring the published Review
Summary rubric's bolded-name-plus-question format (docs/CORPUS-
EXTRACTION.md line 2929). Split out of ``test_prompts_review.py`` to keep
that module within the file-length ceiling.

Production's json_object mode does not enforce the schema, so a live run
can answer with either shape (or garbage); every case here is exercised
against the same review-prompt injection path
(``prompts/review.py::_format_review_phase_guidance``).
"""

from __future__ import annotations

from co_scientist.prompts import PromptRunContext, get_review_prompt


def test_review_prompt_critical_criteria_structured_shape() -> None:
    """The richer {name, questions} shape surfaces both levels of names.

    Criterion name, question name, and question text all reach the review
    prompt -- matching the published Review Summary rubric
    (docs/CORPUS-EXTRACTION.md line 2929).
    """
    guidance = {
        "workflow_plan": {
            "review_phase": {
                "critical_criteria": [
                    {
                        "name": "Kinetic Feasibility",
                        "questions": [
                            {
                                "name": "Biological Timeframe Consistency",
                                "question": (
                                    "Does the design account for the"
                                    " mechanism's kinetics?"
                                ),
                            },
                            {
                                "name": "Kinetic Competition",
                                "question": (
                                    "Does degradation outpace synthesis?"
                                ),
                            },
                        ],
                    }
                ]
            }
        }
    }
    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(supervisor_guidance=guidance),
    )
    assert "Kinetic Feasibility" in prompt
    assert "Biological Timeframe Consistency" in prompt
    assert "Does the design account for the mechanism's kinetics?" in prompt
    assert "Kinetic Competition" in prompt
    assert "Does degradation outpace synthesis?" in prompt


def test_review_prompt_critical_criteria_legacy_shape() -> None:
    """A bare list of strings (pre-R12-23 persisted shape) still renders."""
    guidance = {
        "workflow_plan": {
            "review_phase": {
                "critical_criteria": ["novelty", "testability"],
            }
        }
    }
    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(supervisor_guidance=guidance),
    )
    assert "novelty" in prompt
    assert "testability" in prompt


def test_review_prompt_critical_criteria_caps_count_and_questions() -> None:
    """A live run's uncapped answer is defensively re-sliced at injection.

    json_object mode (the production downgrade path) does not enforce the
    schema's maxItems server-side, so this caps to Google's own published
    counts (5 criteria, 4 questions each) regardless of what the model
    actually returned -- the same defense research_overview_directions.py
    applies for its own nested lists.
    """
    guidance = {
        "workflow_plan": {
            "review_phase": {
                "critical_criteria": [
                    {
                        "name": f"criterion {i}",
                        "questions": [
                            {"name": f"q{i}-{j}", "question": f"text {i}-{j}?"}
                            for j in range(6)
                        ],
                    }
                    for i in range(8)
                ]
            }
        }
    }
    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(supervisor_guidance=guidance),
    )
    assert "criterion 4" in prompt
    assert "criterion 5" not in prompt
    assert "text 0-3?" in prompt
    assert "text 0-4?" not in prompt


def test_review_prompt_critical_criteria_malformed_entries_degrade() -> None:
    """Malformed entries are skipped, not raised, alongside valid ones."""
    guidance = {
        "workflow_plan": {
            "review_phase": {
                "critical_criteria": [
                    {"name": "Valid Criterion", "questions": ["plain text q"]},
                    {"name": ""},
                    {"questions": []},
                    42,
                    None,
                ],
            }
        }
    }
    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(supervisor_guidance=guidance),
    )
    assert "Valid Criterion" in prompt
    assert "plain text q" in prompt


def test_review_prompt_critical_criteria_absent_renders_no_section() -> None:
    """No critical_criteria means no 'Critical Criteria to Emphasize' line."""
    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(
            supervisor_guidance={
                "workflow_plan": {"review_phase": {"review_depth": "deep"}}
            }
        ),
    )
    assert "Critical Criteria to Emphasize" not in prompt
    assert "Review Depth Required" in prompt
