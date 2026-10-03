from typing import Any

from app.report import markdown as report_markdown
from app.report.markdown.overview import render_research_overview_markdown


def _criteria_markdown(
    critical_criteria: list[Any] | None,
    setup: dict[str, object] | None = None,
) -> str:
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
            critical_criteria=critical_criteria,
            setup=setup,
        )
    )


def test_criteria_render_as_a_bullet_list() -> None:
    markdown = _criteria_markdown(
        [
            "Kinetic Feasibility and Experimental Readouts",
            "Human Data Integration and Accuracy",
        ]
    )

    assert "## Evaluation Criteria" in markdown
    assert "Kinetic Feasibility and Experimental Readouts" in markdown
    assert "Human Data Integration and Accuracy" in markdown


def test_no_critical_criteria_renders_no_section() -> None:
    assert "Evaluation Criteria" not in _criteria_markdown(None)
    assert "Evaluation Criteria" not in _criteria_markdown([])


def test_all_blank_criteria_render_no_section() -> None:
    markdown = _criteria_markdown(["", "   "])

    assert "Evaluation Criteria" not in markdown


def test_criteria_render_from_the_structured_shape() -> None:
    # Reviewer questions belong to Review Summary rather than the flat
    # evaluation-criteria list.
    markdown = _criteria_markdown(
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
    markdown = _criteria_markdown("not a list")  # type: ignore[arg-type]

    assert "Evaluation Criteria" not in markdown


def test_criteria_render_with_description() -> None:
    markdown = _criteria_markdown(
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
    markdown = _criteria_markdown(
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
    markdown = _criteria_markdown(
        [{"name": "Safety and Therapeutic Viability", "description": "   "}]
    )

    assert "- Safety and Therapeutic Viability" in markdown
    assert "**Safety and Therapeutic Viability:**" not in markdown


def test_mixed_shapes_each_render_in_their_own_form() -> None:
    markdown = _criteria_markdown(
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
    markdown = _criteria_markdown(
        [
            42,
            None,
            ["not", "a", "criterion"],
            {"name": "Valid Criterion", "description": "Valid prose."},
        ]
    )

    assert "**Valid Criterion:** Valid prose." in markdown


def test_distinct_from_the_user_authored_criteria_list() -> None:
    # Synthesized reviewer criteria and scientist-authored criteria are distinct
    # inputs.
    markdown = _criteria_markdown(
        ["Mechanistic Novelty and Rigor in Fibrosis Reversal"],
        setup={"criteria": ["should be testable within two years"]},
    )

    assert "## Evaluation Criteria" in markdown
    assert "Mechanistic Novelty and Rigor in Fibrosis Reversal" in markdown
    assert "**Criteria:**" in markdown
    assert "should be testable within two years" in markdown


def _render_main_directions_report(
    meta_review: dict[str, object] | None,
) -> str:
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
    markdown = _render_main_directions_report(
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
    markdown = _render_main_directions_report(
        {"main_research_directions": "First paragraph.\n\nSecond paragraph."}
    )

    directions_index = markdown.index("## Main Research Directions")
    candidates_index = markdown.index("## Top hypotheses")
    assert directions_index < candidates_index


def test_no_bare_heading_when_the_field_is_absent() -> None:
    markdown = _render_main_directions_report(
        {"summary": "some other synthesis"}
    )

    assert "Main Research Directions" not in markdown


def test_no_bare_heading_when_meta_review_is_none() -> None:
    markdown = _render_main_directions_report(None)

    assert "Main Research Directions" not in markdown


def test_no_bare_heading_when_the_field_is_blank() -> None:
    markdown = _render_main_directions_report(
        {"main_research_directions": "   "}
    )

    assert "Main Research Directions" not in markdown


def _meta_review_markdown(meta_review: dict[str, object]) -> str:
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


def test_a_structured_theme_renders_its_description_and_frequency() -> None:
    markdown = _meta_review_markdown(
        {
            "recurring_themes": [
                {
                    "theme": "Motor neuron specificity",
                    "description": (
                        "Ideas rarely explain why the mechanism would"
                        " preferentially affect motor neurons."
                    ),
                    "frequency": "common",
                }
            ]
        }
    )

    assert "### Emerging themes" in markdown
    assert "Motor neuron specificity" in markdown
    assert "preferentially affect motor neurons" in markdown
    assert "common" in markdown


def test_a_bare_theme_name_falls_back_to_a_plain_bullet() -> None:
    markdown = _meta_review_markdown(
        {"emerging_themes": ["Time-resolved state measurements"]}
    )

    assert "### Emerging themes" in markdown
    assert "- Time-resolved state measurements" in markdown


def test_an_entry_with_no_theme_name_is_skipped() -> None:
    # The disclosure legitimately contains **:; only the empty-name ****: form
    # exposes this bug.
    markdown = _meta_review_markdown(
        {
            "recurring_themes": [
                {"theme": "", "description": "orphaned text", "frequency": ""}
            ]
        }
    )

    assert "orphaned text" not in markdown
    assert "****:" not in markdown


def test_a_theme_renders_its_sub_themes_and_their_points() -> None:
    markdown = _meta_review_markdown(
        {
            "recurring_themes": [
                {
                    "theme": "Core Hypothesis and Mechanism",
                    "description": "How the mechanism itself is argued.",
                    "frequency": "very common",
                    "sub_themes": [
                        {
                            "theme": "Primary Driver vs. Consequence",
                            "description": "Whether it initiates or follows.",
                            "points": [
                                "Provide evidence for the temporal sequence.",
                                "Knock the driver down to show necessity.",
                            ],
                        }
                    ],
                }
            ]
        }
    )

    assert "#### Core Hypothesis and Mechanism" in markdown
    assert "- **Primary Driver vs. Consequence**: Whether it" in markdown
    assert "  - Provide evidence for the temporal sequence." in markdown
    assert "  - Knock the driver down to show necessity." in markdown


def test_a_flat_theme_from_an_older_checkpoint_still_renders() -> None:
    # Checkpointed flat themes survive schema changes and must remain readable.
    markdown = _meta_review_markdown(
        {
            "recurring_themes": [
                {
                    "theme": "Motor neuron specificity",
                    "description": "Rarely explained.",
                    "frequency": "common",
                }
            ]
        }
    )

    assert "#### Motor neuron specificity" in markdown
    assert "Rarely explained." in markdown


def test_a_sub_theme_with_no_points_renders_as_a_plain_bullet() -> None:
    markdown = _meta_review_markdown(
        {
            "recurring_themes": [
                {
                    "theme": "Novelty and Impact",
                    "description": "",
                    "frequency": "",
                    "sub_themes": [
                        {
                            "theme": "Incremental vs. Groundbreaking",
                            "description": "Builds on existing knowledge.",
                            "points": [],
                        }
                    ],
                }
            ]
        }
    )

    assert "#### Novelty and Impact" in markdown
    assert (
        "- **Incremental vs. Groundbreaking**: Builds on existing knowledge."
        in markdown
    )


def test_a_bare_string_sub_theme_still_renders() -> None:
    markdown = _meta_review_markdown(
        {
            "recurring_themes": [
                {
                    "theme": "Assumptions and Validation",
                    "sub_themes": ["State every assumption explicitly."],
                }
            ]
        }
    )

    assert "- State every assumption explicitly." in markdown


def _questions_markdown(payload: dict[str, object]) -> str:
    return "\n".join(render_research_overview_markdown(payload))


def test_open_questions_render_as_a_numbered_list() -> None:
    markdown = _questions_markdown(
        {
            "open_questions": [
                "To what extent can X be targeted to reverse Y?",
                "How does the crosstalk between A and B modulate C?",
            ]
        }
    )

    assert "## Open questions" in markdown
    assert "1. To what extent can X be targeted to reverse Y?" in markdown
    assert "2. How does the crosstalk between A and B modulate C?" in markdown


def test_clear_and_unexpected_patterns_render_as_labelled_bullet_lists() -> (
    None
):
    markdown = _questions_markdown(
        {
            "clear_patterns": ["Lipid handling recurs across every idea."],
            "unexpected_patterns": [
                "A metabolic block explains a proteolysis failure."
            ],
        }
    )

    assert "### Clear patterns" in markdown
    assert "Lipid handling recurs across every idea." in markdown
    assert "### Unexpected patterns" in markdown
    assert "A metabolic block explains a proteolysis failure." in markdown


def test_no_open_questions_or_patterns_renders_no_section() -> None:
    markdown = _questions_markdown({"overview": {"summary": "S"}})

    assert "Open questions" not in markdown
    assert "Clear patterns" not in markdown
    assert "Unexpected patterns" not in markdown


def test_a_json_string_open_question_is_flattened() -> None:
    markdown = _questions_markdown(
        {"open_questions": ['{"question": "What drives X?"}']}
    )

    assert "What drives X?" in markdown
    assert '{"question"' not in markdown


def test_the_section_is_named_recommendation_and_strategic_roadmap() -> None:
    markdown = _meta_review_markdown(
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
    markdown = _meta_review_markdown(
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
    markdown = _meta_review_markdown(
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
    markdown = _meta_review_markdown(
        {"strategic_recommendations": ["Only one recommendation."]}
    )

    assert "**Primary recommendation:** Only one recommendation." in markdown
    roadmap_section = markdown.split(
        "### Recommendation and strategic roadmap"
    )[1]
    assert "1." not in roadmap_section


def test_no_recommendations_renders_no_section() -> None:
    markdown = _meta_review_markdown({"summary": "Nothing to recommend yet."})

    assert "Recommendation and strategic roadmap" not in markdown


def test_time_estimate_renders_as_a_parenthetical_suffix() -> None:
    markdown = _meta_review_markdown(
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
    markdown = _meta_review_markdown(
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
    markdown = _meta_review_markdown(
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
    markdown = _meta_review_markdown(
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


def _attributes_markdown(
    attributes: list[dict[str, object]] | None,
    setup: dict[str, object] | None = None,
) -> str:
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
            attributes=attributes,
            setup=setup,
        )
    )


def test_attributes_render_as_named_rating_scales() -> None:
    markdown = _attributes_markdown(
        [
            {
                "name": "Mechanism Novelty",
                "rubric": (
                    "1: Well-established pathway, 3: New application of a"
                    " known mechanism, 5: Highly novel and"
                    " paradigm-shifting."
                ),
            },
            {
                "name": "Target Area",
                "rubric": (
                    "Categorize the primary focus of the hypothesis"
                    " (Epigenetics, Stellate Cell Biology, or"
                    " Stromal-Immune Crosstalk)."
                ),
            },
        ]
    )

    assert "## Stratification Attributes" in markdown
    assert "Mechanism Novelty" in markdown
    assert "Highly novel and paradigm-shifting." in markdown
    assert "Target Area" in markdown
    assert "Stromal-Immune Crosstalk" in markdown


def test_no_attributes_renders_no_section() -> None:
    assert "Stratification Attributes" not in _attributes_markdown(None)
    assert "Stratification Attributes" not in _attributes_markdown([])


def test_an_attribute_with_no_name_is_skipped() -> None:
    markdown = _attributes_markdown([{"rubric": "orphaned rubric text"}])

    assert "orphaned rubric text" not in markdown
    assert "Stratification Attributes" not in markdown


def test_distinct_from_the_user_authored_attributes_list() -> None:
    # Synthesized stratification attributes and scientist-authored attributes
    # are distinct inputs.
    markdown = _attributes_markdown(
        [{"name": "Human Relevance", "rubric": "1-5 scale rubric text."}],
        setup={"attributes": ["Should be testable in human tissue"]},
    )

    assert "## Stratification Attributes" in markdown
    assert "Human Relevance" in markdown
    assert "**Attributes:**" in markdown
    assert "Should be testable in human tissue" in markdown


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
                    "synthesis_opportunity": (
                        "Both ideas converge on mitochondrial calcium"
                        " uptake and could share a validation assay."
                    ),
                }
            ]
        }
    )

    assert "Unexpected connections" in markdown
    assert "Fluspirilene (Hypothesis 1)" in markdown
    assert "NHE1 blockade (Hypothesis 3)" in markdown
    assert "Shared calcium-handling mechanism" in markdown
    assert "share a validation assay" in markdown


def test_no_connections_renders_no_section() -> None:
    markdown = _meta_review_markdown(
        {"summary": "A synthesis with no cross-links."}
    )

    assert "Unexpected connections" not in markdown


def test_a_malformed_connection_entry_is_skipped_not_stringified() -> None:
    markdown = _meta_review_markdown({"potential_connections": ["not a dict"]})

    assert "not a dict" not in markdown


def _render_unexpected_directions(payload: dict[str, object]) -> str:
    return "\n".join(render_research_overview_markdown(payload))


def test_unexpected_directions_render_as_bolded_name_plus_prose_bullets() -> (
    None
):
    markdown = _render_unexpected_directions(
        {
            "overview": {
                "summary": "S",
                "research_directions": [
                    {"title": "A", "importance": "I"},
                    {"title": "B", "importance": "I"},
                ],
            },
            "unexpected_research_directions": [
                {
                    "title": "Nuclear LOXL2 as a Histone Modifier",
                    "description": (
                        "Beyond crosslinking collagen, nuclear-translocated"
                        " LOXL2 may act as a histone aminooxidase."
                    ),
                }
            ],
        }
    )

    assert "### Unexpected research directions" in markdown
    assert (
        "- **Nuclear LOXL2 as a Histone Modifier:** Beyond crosslinking"
        " collagen, nuclear-translocated LOXL2 may act as a histone"
        " aminooxidase."
    ) in markdown


def test_section_sits_adjacent_to_the_directions_content() -> None:
    markdown = _render_unexpected_directions(
        {
            "overview": {
                "summary": "S",
                "research_directions": [{"title": "A", "importance": "I"}],
            },
            "unexpected_research_directions": [
                {"title": "X", "description": "Y"}
            ],
        }
    )

    overview_index = markdown.index("## Research Overview")
    directions_index = markdown.index("### A")
    unexpected_index = markdown.index("### Unexpected research directions")
    open_questions_index = markdown.find("## Open questions")

    assert overview_index < directions_index < unexpected_index
    assert open_questions_index == -1 or unexpected_index < open_questions_index


def test_no_unexpected_directions_renders_no_heading() -> None:
    markdown = _render_unexpected_directions(
        {"overview": {"summary": "S", "research_directions": []}}
    )

    assert "Unexpected research directions" not in markdown


def test_an_entry_with_no_description_still_renders_its_title() -> None:
    markdown = _render_unexpected_directions(
        {
            "overview": {"summary": "S", "research_directions": []},
            "unexpected_research_directions": [{"title": "Bare title"}],
        }
    )

    assert "- Bare title" in markdown
    assert "- **Bare title:**" not in markdown


def test_a_json_string_description_is_flattened() -> None:
    markdown = _render_unexpected_directions(
        {
            "overview": {"summary": "S", "research_directions": []},
            "unexpected_research_directions": [
                {
                    "title": "X",
                    "description": '{"claim": "worth pursuing"}',
                }
            ],
        }
    )

    assert "worth pursuing" in markdown
    assert '{"claim"' not in markdown
