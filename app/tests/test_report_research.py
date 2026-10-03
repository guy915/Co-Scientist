"""Tests for report research."""

from typing import Any

from app.report import markdown as report_markdown
from app.report.markdown.overview import render_research_overview_markdown

# R12-18: the report renders the Supervisor's synthesized evaluation criteria.
#
# The published MASH plan carries a "## **2. Evaluation Criteria**" section:
# goal-specific criteria synthesized for that run, with names like "Kinetic
# Feasibility and Experimental Readouts" and "Human Data Integration and
# Accuracy" (``docs/CORPUS-EXTRACTION.md``, MASH body). The Supervisor
# already synthesizes this list as ``workflow_plan.review_phase.
# critical_criteria`` and ``prompts/review.py`` already injects it into
# every reviewer prompt as "Critical Criteria to Emphasize" -- but nothing
# ever rendered it to the reader. This pins that the markdown export now
# does, under a heading distinct from the run's user-authored "Criteria"
# bullet list under "Research Goal Details" (a different, plain-string field
# from ``run_modes.DEFAULT_CRITERIA`` or the user's own setup -- see the
# ``report_markdown`` module's vocabulary warning: "Criteria" names two
# differently-shaped things, one user-authored and one model-synthesized,
# and conflating them would present the model's synthesis as the user's
# own setup).


def _criteria_markdown(
    critical_criteria: list[Any] | None,
    setup: dict[str, object] | None = None,
) -> str:
    """Render a minimal report carrying only the given critical criteria."""
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
    """Each synthesized criterion prints as its own bullet."""
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
    """An absent criteria list emits no heading, not an empty one."""
    assert "Evaluation Criteria" not in _criteria_markdown(None)
    assert "Evaluation Criteria" not in _criteria_markdown([])


def test_all_blank_criteria_render_no_section() -> None:
    """Entries that are blank strings contribute nothing renderable."""
    markdown = _criteria_markdown(["", "   "])

    assert "Evaluation Criteria" not in markdown


def test_criteria_render_from_the_structured_shape() -> None:
    """R12-23: the flat list still renders names from the richer shape.

    critical_criteria may carry {name, questions} entries; this section
    only extracts the name -- the questions belong to the separate
    'Review Summary' section.
    """
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
    """A field that is not a list at all degrades to nothing, not a crash."""
    markdown = _criteria_markdown("not a list")  # type: ignore[arg-type]

    assert "Evaluation Criteria" not in markdown


def test_criteria_render_with_description() -> None:
    """R12-23b: a criterion carrying prose renders Google's own shape.

    docs/CORPUS-EXTRACTION.md line 2558's section is a bolded name, a
    colon, then a prose paragraph -- not a bare name bullet.
    """
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
    """A {name, questions} entry with no description degrades to a bullet.

    Covers both a legacy pre-R12-23b dict and a live run whose answer
    omitted description under the json_object downgrade -- degrade,
    never drop, never crash.
    """
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
    """A whitespace-only description is treated as absent, not rendered."""
    markdown = _criteria_markdown(
        [{"name": "Safety and Therapeutic Viability", "description": "   "}]
    )

    assert "- Safety and Therapeutic Viability" in markdown
    assert "**Safety and Therapeutic Viability:**" not in markdown


def test_mixed_shapes_each_render_in_their_own_form() -> None:
    """A run mixing the description shape with legacy entries renders both."""
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
    """An int/None/list entry contributes nothing; valid ones still render."""
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
    """The synthesized section never replaces the user-authored list.

    It coexists with the user-authored "Criteria" bullet list rendered
    under "Research Goal Details" -- same English word, two different
    published sections, see the module docstring's vocabulary warning.
    """
    markdown = _criteria_markdown(
        ["Mechanistic Novelty and Rigor in Fibrosis Reversal"],
        setup={"criteria": ["should be testable within two years"]},
    )

    assert "## Evaluation Criteria" in markdown
    assert "Mechanistic Novelty and Rigor in Fibrosis Reversal" in markdown
    assert "**Criteria:**" in markdown
    assert "should be testable within two years" in markdown


# R14-27: the report's own "Main Research Directions" section.
#
# Google's published ranking report carries a narrative synthesis distinct
# from any itemized directions array -- two prose paragraphs weaving the
# run's directions together (``.../ai-guided-discovery-of-atypical-protein-
# assemblies/reports/top-ranking-hypotheses.md:24-28``), sitting immediately
# before Candidate Ideas -- this repo's Top hypotheses section. This pins
# that ``meta_review.main_research_directions`` renders there, in that
# position, and skips cleanly (no bare heading) when absent -- a legacy run
# persisted before this field existed, or a provider that omits it under
# json_object mode.


def _render_main_directions_report(
    meta_review: dict[str, object] | None,
) -> str:
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
    """Matches the published "before Candidate Ideas" placement."""
    markdown = _render_main_directions_report(
        {"main_research_directions": "First paragraph.\n\nSecond paragraph."}
    )

    directions_index = markdown.index("## Main Research Directions")
    candidates_index = markdown.index("## Top hypotheses")
    assert directions_index < candidates_index


def test_no_bare_heading_when_the_field_is_absent() -> None:
    """A legacy meta_review with no field at all renders no heading."""
    markdown = _render_main_directions_report(
        {"summary": "some other synthesis"}
    )

    assert "Main Research Directions" not in markdown


def test_no_bare_heading_when_meta_review_is_none() -> None:
    """No meta_review at all (a run with no synthesis) renders no heading."""
    markdown = _render_main_directions_report(None)

    assert "Main Research Directions" not in markdown


def test_no_bare_heading_when_the_field_is_blank() -> None:
    """An explicitly empty string degrades to nothing, not an empty heading."""
    markdown = _render_main_directions_report(
        {"main_research_directions": "   "}
    )

    assert "Main Research Directions" not in markdown


# MO-2: the "Emerging themes" section renders the full theme taxonomy.
#
# Google's published meta-review critique
# (``meta-review-critiques/als-meta-review-critique.md``) organizes the
# recurring critiques as five themes, three levels deep: a theme, the named
# critique points under it, and the guidance sub-points under several of
# those. Our schema flattened all of that to ``{theme, description,
# frequency}``; both halves of that loss are now closed -- ``meta_review.py``
# used to drop ``description``/``frequency`` before the state dict reached
# the app (so the section printed bare theme names for fields the model was
# paid to compute), and the schema itself carried no nesting to render.
#
# These pin the three levels of real markdown hierarchy, and the three input
# shapes that must all render: the nested taxonomy, the flat entry a run
# checkpointed before ``sub_themes`` existed still carries, and the
# bare-name ``emerging_themes`` fallback of a demo/seed report.


def _themes_markdown(meta_review: dict[str, object]) -> str:
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


def test_a_structured_theme_renders_its_description_and_frequency() -> None:
    """A recurring_themes entry prints its description and frequency."""
    markdown = _themes_markdown(
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
    """A report with only the flattened list still renders, bare-named.

    Covers demo/seed reports and any report persisted before
    ``recurring_themes`` existed -- ``emerging_themes`` alone must not
    regress to a missing section.
    """
    markdown = _themes_markdown(
        {"emerging_themes": ["Time-resolved state measurements"]}
    )

    assert "### Emerging themes" in markdown
    assert "- Time-resolved state measurements" in markdown


def test_an_entry_with_no_theme_name_is_skipped() -> None:
    """A malformed entry with an empty theme does not render a bare '****:'.

    ``**:`` alone is too loose a check -- R14-13's per-hypothesis disclaimer
    ("**About**: ...") legitimately contains it. The bug this guards is an
    empty name reaching ``f"**{name}**: {description}"`` and rendering the
    doubled-asterisk ``****:`` that produces.
    """
    markdown = _themes_markdown(
        {
            "recurring_themes": [
                {"theme": "", "description": "orphaned text", "frequency": ""}
            ]
        }
    )

    assert "orphaned text" not in markdown
    assert "****:" not in markdown


def test_a_theme_renders_its_sub_themes_and_their_points() -> None:
    """MO-2: three real levels of hierarchy, not a flattened dump.

    The published critique nests a named critique point under each theme
    and guidance sub-points under several of those points; the renderer
    must show that as a heading, a bullet, and a sub-bullet rather than
    running them together.
    """
    markdown = _themes_markdown(
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
    """A resumed run persisted before sub-themes existed must not crash.

    ``meta_review`` is checkpointed state, so the flat three-field entry
    outlives the schema change; it renders as a theme with no sub-list.
    """
    markdown = _themes_markdown(
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
    """Two of the published themes carry points with no sub-points at all."""
    markdown = _themes_markdown(
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
    """json_object mode enforces nothing, so a sub-theme may be a string."""
    markdown = _themes_markdown(
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


# R12-10: open questions and cross-cutting patterns render in the overview.
#
# The MASH Goal Report carries top-level ``Open Questions``, ``Clear
# Patterns:``, and ``Unexpected Patterns:`` sections
# (``docs/CORPUS-EXTRACTION.md`` R12-10). The research-overview synthesis --
# the terminal cross-hypothesis narrative -- is the natural home: Google's own
# second exemplar (``research-overview.md``, R14-1) lists ``Open questions``
# beside its research-directions summary in that same document family, one
# level up from where our ``Unexpected connections``/``Recommendation``
# sections already live in ``meta_review``.


def _questions_markdown(payload: dict[str, object]) -> str:
    """Render the overview payload to a single markdown string."""
    return "\n".join(render_research_overview_markdown(payload))


def test_open_questions_render_as_a_numbered_list() -> None:
    """Each open question numbers from 1, matching the published list."""
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
    """Both pattern lists render under their own published-name headings."""
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
    """Absent/empty fields emit no heading -- ours, not Google's convention."""
    markdown = _questions_markdown({"overview": {"summary": "S"}})

    assert "Open questions" not in markdown
    assert "Clear patterns" not in markdown
    assert "Unexpected patterns" not in markdown


def test_a_json_string_open_question_is_flattened() -> None:
    """Matches this module's established json_object-downgrade coercion."""
    markdown = _questions_markdown(
        {"open_questions": ['{"question": "What drives X?"}']}
    )

    assert "What drives X?" in markdown
    assert '{"question"' not in markdown


# R12-11: strategic recommendations render as a staged roadmap.
#
# The MASH Goal Report's ``9 Recommendation and Strategic Roadmap`` names a
# primary recommendation, then sequences four named phases each with
# concrete next steps (``docs/CORPUS-EXTRACTION.md`` R12-11). Our
# ``strategic_recommendations`` is a flat list of
# ``{focus_area, recommendation, justification}`` with no phase name,
# dependency, or ordering field -- so named phases with assays would be
# invented content the schema cannot support. This is a presentation
# change only: the first recommendation is distinguished as the primary
# one and the rest render as a numbered roadmap, matching what the data
# actually carries.


def _roadmap_markdown(meta_review: dict[str, object]) -> str:
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
    markdown = _roadmap_markdown(
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
    markdown = _roadmap_markdown(
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
    markdown = _roadmap_markdown(
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
    markdown = _roadmap_markdown(
        {"strategic_recommendations": ["Only one recommendation."]}
    )

    assert "**Primary recommendation:** Only one recommendation." in markdown
    roadmap_section = markdown.split(
        "### Recommendation and strategic roadmap"
    )[1]
    assert "1." not in roadmap_section


def test_no_recommendations_renders_no_section() -> None:
    """An empty list emits no heading at all."""
    markdown = _roadmap_markdown({"summary": "Nothing to recommend yet."})

    assert "Recommendation and strategic roadmap" not in markdown


def test_time_estimate_renders_as_a_parenthetical_suffix() -> None:
    """R14-8: a step's timeline appends after its recommendation text."""
    markdown = _roadmap_markdown(
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
    markdown = _roadmap_markdown(
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
    markdown = _roadmap_markdown(
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
    markdown = _roadmap_markdown(
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


# R12-17: the report renders the Supervisor's synthesized attributes.
#
# The published MASH plan prints its run Attributes at the top of the
# report, as named rating scales: four carrying a 1-5 scale with worked
# anchor examples, plus one categorical scale with a fixed value set
# (``docs/CORPUS-EXTRACTION.md`` R12-17, Appendix C). The Supervisor already
# synthesizes this shape as ``config_synthesis.attributes`` and
# ``prompts/review.py`` already injects it into every reviewer prompt as
# "Stratification attributes (score each 1-5)" -- but nothing ever rendered
# it to the reader. This pins that the markdown export now does, under a
# heading distinct from the run's user-authored "Attributes" bullet list
# under "Research Goal Details" (a different, plain-string field -- see the
# CORPUS-EXTRACTION.md mirror-pass-1 vocabulary warning: "Attributes" names
# two differently-shaped things in Google's own documents, and conflating
# them would reproduce the wrong one).


def _attributes_markdown(
    attributes: list[dict[str, object]] | None,
    setup: dict[str, object] | None = None,
) -> str:
    """Render a minimal report carrying only the given attributes."""
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
    """Each synthesized attribute prints its name and 1-5 rubric."""
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
    """An absent attributes list emits no heading, not an empty one."""
    assert "Stratification Attributes" not in _attributes_markdown(None)
    assert "Stratification Attributes" not in _attributes_markdown([])


def test_an_attribute_with_no_name_is_skipped() -> None:
    """A malformed attribute with no name contributes nothing renderable."""
    markdown = _attributes_markdown([{"rubric": "orphaned rubric text"}])

    assert "orphaned rubric text" not in markdown
    assert "Stratification Attributes" not in markdown


def test_distinct_from_the_user_authored_attributes_list() -> None:
    """The synthesized section never replaces the user-authored list.

    It coexists with the user-authored "Attributes" bullet list rendered
    under "Research Goal Details"
    -- same English word, two different published sections, see the
    module docstring's vocabulary warning.
    """
    markdown = _attributes_markdown(
        [{"name": "Human Relevance", "rubric": "1-5 scale rubric text."}],
        setup={"attributes": ["Should be testable in human tissue"]},
    )

    assert "## Stratification Attributes" in markdown
    assert "Human Relevance" in markdown
    assert "**Attributes:**" in markdown
    assert "Should be testable in human tissue" in markdown


# R12-7: the report surfaces the meta-review's cross-idea connections.
#
# The MASH Goal Report carries an ``8 Key Findings and Unexpected Molecular
# Connections`` section and a top-level ``Unexpected Connections`` section
# (``docs/CORPUS-EXTRACTION.md`` R12-7). The engine already computes this --
# ``agents/meta_review/meta_review.py`` produces ``potential_connections`` and
# ``prompts/_common.py`` re-injects it into downstream prompts -- but
# ``_META_REVIEW_BULLET_SECTIONS`` never rendered it, so it was paid for and
# discarded. Google's exemplar entries are not reproduced here: the published
# four-field shape (Claims/Reasoning/Novelty/Relevance) has no analogue in our
# schema, which computes ``related_hypotheses`` (short subject labels, e.g.
# "Fluspirilene (Hypothesis 1)"), ``connection_type``, and
# ``synthesis_opportunity`` instead -- so this renders those real fields under
# the published section name rather than inventing novelty/relevance verdicts
# that were never judged.


def _connections_markdown(meta_review: dict[str, object]) -> str:
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


def test_a_connection_renders_its_related_hypotheses_type_and_opportunity() -> (
    None
):
    """A structured connection entry prints all three of its real fields."""
    markdown = _connections_markdown(
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
    """An empty or absent potential_connections list emits no heading."""
    markdown = _connections_markdown(
        {"summary": "A synthesis with no cross-links."}
    )

    assert "Unexpected connections" not in markdown


def test_a_malformed_connection_entry_is_skipped_not_stringified() -> None:
    """A non-dict entry never leaks a raw Python repr into the report."""
    markdown = _connections_markdown({"potential_connections": ["not a dict"]})

    assert "not a dict" not in markdown


# Task B: 'Unexpected research directions' renders in the overview.
#
# MASH's own published exemplar carries a fourth block, ``Unexpected
# Research Directions``, directly beneath its expanded restatement of the
# five main directions (``docs/CORPUS-EXTRACTION.md``, .../mash-liver-
# fibrosis-reversal-therapeutic-hypothesis.md:418) -- three bolded-name-
# plus-prose bullets naming genuinely novel strategic directions, not a
# repeat of the main research_directions and not the same thing as
# ``unexpected_patterns`` (R12-10, a pattern observed across the ideas,
# not a direction worth pursuing).


def _render_unexpected_directions(payload: dict[str, object]) -> str:
    """Render the overview payload to a single markdown string."""
    return "\n".join(render_research_overview_markdown(payload))


def test_unexpected_directions_render_as_bolded_name_plus_prose_bullets() -> (
    None
):
    """Each entry renders its title bolded, followed by its prose."""
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
    """The block renders inside 'Research Overview', after the directions."""
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
    # Still inside the Research Overview section, not the next one.
    assert open_questions_index == -1 or unexpected_index < open_questions_index


def test_no_unexpected_directions_renders_no_heading() -> None:
    """Absent/empty field emits no heading -- legacy runs must not regress."""
    markdown = _render_unexpected_directions(
        {"overview": {"summary": "S", "research_directions": []}}
    )

    assert "Unexpected research directions" not in markdown


def test_an_entry_with_no_description_still_renders_its_title() -> None:
    """Degrade, never drop -- a bare title bullet with no colon."""
    markdown = _render_unexpected_directions(
        {
            "overview": {"summary": "S", "research_directions": []},
            "unexpected_research_directions": [{"title": "Bare title"}],
        }
    )

    assert "- Bare title" in markdown
    assert "- **Bare title:**" not in markdown


def test_a_json_string_description_is_flattened() -> None:
    """Matches this module's established json_object-downgrade coercion."""
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
