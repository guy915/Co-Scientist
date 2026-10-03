"""Offline contracts for prompts review."""

from __future__ import annotations

import pathlib
from typing import Any

from co_scientist.prompts import (
    PromptRunContext,
    RankingSide,
    SupervisorPromptInputs,
    get_meta_review_prompt,
    get_proximity_prompt,
    get_ranking_prompt,
    get_review_batch_prompt,
    get_review_prompt,
    get_supervisor_prompt,
    load_prompt_with_schema,
    substitute_variables,
)
from co_scientist.prompts.loading import _get_domain_variables
from co_scientist.schemas import _PROMPT_SCHEMA_MAP
from co_scientist.schemas.review import RANKING_SCHEMA

# A supervisor_guidance dict shaped like the real planner output. Used to
# exercise the guidance-formatting branches of several builders.
_GUIDANCE: dict[str, Any] = {
    "research_goal_analysis": {
        "key_areas": ["mitochondrial dysfunction", "oxidative stress"],
    },
    "workflow_plan": {
        "generation_phase": {
            "focus_areas": ["metabolic pathways"],
            "diversity_targets": "broad",
            "quantity_target": 5,
        },
        "review_phase": {
            "critical_criteria": ["novelty", "testability"],
            "review_depth": "deep",
        },
        "evolution_phase": {
            "refinement_priorities": ["specificity"],
            "iteration_strategy": "incremental",
        },
    },
}

# --- pure helpers ----------------------------------------------------------


def test_substitute_variables_replaces_placeholder() -> None:
    """``{{name}}`` placeholders are replaced by the mapped value."""
    assert substitute_variables("Hello {{name}}", {"name": "World"}) == (
        "Hello World"
    )


def test_substitute_variables_coerces_non_string_values() -> None:
    """Non-string values are stringified during substitution."""
    assert substitute_variables("count={{n}}", {"n": 7}) == "count=7"


def test_substitute_variables_missing_key_emits_marker() -> None:
    """An unmapped placeholder yields a ``MISSING`` marker, not a crash."""
    out = substitute_variables("a {{absent}} b", {})
    assert "{{MISSING:absent}}" in out


def test_load_prompt_with_schema_returns_prompt_and_schema() -> None:
    """``load_prompt_with_schema`` returns a filled string and a schema dict.

    This calls the low-level loader with only two of the template's variables,
    so the remaining placeholders stay unfilled; the test asserts only on what
    it supplied (the goal) and the schema shape, not full interpolation.
    """
    prompt, schema = load_prompt_with_schema(
        "review",
        {
            "research_goal": "cure ALS",
            "hypothesis_text": "TDP-43 aggregation",
        },
    )
    assert isinstance(prompt, str)
    assert prompt
    assert "cure ALS" in prompt
    assert isinstance(schema, dict)


def test_load_prompt_with_schema_none_for_unschemaed_prompt() -> None:
    """A prompt with no registered schema returns ``None`` for the schema."""
    _, schema = load_prompt_with_schema("literature_review_synthesis", {})
    assert schema is None


def test_get_domain_variables_none_returns_string_dict() -> None:
    """``_get_domain_variables(None)`` returns expected keys, all strings."""
    variables = _get_domain_variables(None)
    expected_keys = {
        "domain_context",
        "domain_generation_guidance",
        "domain_review_guidance",
        "domain_evolution_guidance",
        "domain_reflection_guidance",
    }
    assert set(variables) == expected_keys
    assert all(isinstance(v, str) for v in variables.values())


# --- get_supervisor_prompt -------------------------------------------------


def test_supervisor_prompt_interpolates_goal_and_counts() -> None:
    """The supervisor prompt embeds the goal and the planning counts."""
    prompt, schema = get_supervisor_prompt(
        SupervisorPromptInputs(
            research_goal="map gut-brain axis signaling",
            initial_hypotheses_count=4,
            max_iterations=3,
            evolution_max_count=6,
        )
    )
    assert isinstance(prompt, str)
    assert prompt
    assert "map gut-brain axis signaling" in prompt
    assert "4" in prompt
    assert "3" in prompt
    assert "6" in prompt
    assert "{{MISSING" not in prompt
    assert isinstance(schema, dict)


def test_supervisor_prompt_constraints_branch_changes_output() -> None:
    """Supplying constraints injects them; omitting them shows the default."""
    with_constraints, _ = get_supervisor_prompt(
        SupervisorPromptInputs(
            research_goal="goal",
            constraints=["budget under 10k", "in-vitro only"],
        )
    )
    without_constraints, _ = get_supervisor_prompt(
        SupervisorPromptInputs(research_goal="goal")
    )
    assert "budget under 10k" in with_constraints
    assert "budget under 10k" not in without_constraints
    assert "None provided" in without_constraints


def test_supervisor_prompt_pubmed_availability_branch() -> None:
    """PubMed/MCP availability flips the literature-review description text."""
    available, _ = get_supervisor_prompt(
        SupervisorPromptInputs(research_goal="g", pubmed_available=True)
    )
    unavailable, _ = get_supervisor_prompt(
        SupervisorPromptInputs(
            research_goal="g", pubmed_available=False, mcp_available=False
        )
    )
    assert "search pubmed" in available.lower()
    assert "not available" in unavailable.lower()


def test_prompt_builders_include_run_setup_guidance() -> None:
    """Durable setup guidance is embedded in node prompts."""
    setup_guidance = "Run setup:\n- Requirements:\n  - Focus on primary data"
    focus_guidance = "Prefer novelty while preserving testability."
    prompt, _ = get_supervisor_prompt(
        SupervisorPromptInputs(research_goal="g", criteria=["Causal clarity"]),
        PromptRunContext(
            run_setup_guidance=setup_guidance,
            run_focus_guidance=focus_guidance,
        ),
    )
    assert "Run Setup Guidance" in prompt
    assert "Run Focus Guidance" in prompt
    assert "Focus on primary data" in prompt
    assert "Prefer novelty" in prompt
    assert "Causal clarity" in prompt


# --- get_review_prompt / get_review_batch_prompt ---------------------------


def test_review_prompt_interpolates_goal_and_hypothesis() -> None:
    """The review prompt embeds both the research goal and hypothesis text."""
    prompt, schema = get_review_prompt(
        research_goal="explain long-COVID fatigue",
        hypothesis_text="Persistent viral antigen drives T-cell exhaustion",
    )
    assert isinstance(prompt, str)
    assert "explain long-COVID fatigue" in prompt
    assert "Persistent viral antigen drives T-cell exhaustion" in prompt
    assert "{{MISSING" not in prompt
    assert isinstance(schema, dict)


def test_review_prompt_supervisor_guidance_branch() -> None:
    """Supervisor guidance adds a review-guidance section to the prompt."""
    without_guidance, _ = get_review_prompt(
        research_goal="g", hypothesis_text="h"
    )
    with_guidance, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(supervisor_guidance=_GUIDANCE),
    )
    assert len(with_guidance) > len(without_guidance)
    assert "Supervisor Guidance for Review" in with_guidance
    assert "testability" in with_guidance


def test_review_prompt_surfaces_synthesized_config() -> None:
    """config_synthesis lands its fields in the review prompt.

    Covers preferences, review_instructions, and attributes (with their
    1-5 rubric).
    """
    guidance = {
        "config_synthesis": {
            "preferences": ["testable within 2 years"],
            "review_instructions": [
                "penalize ideas that restate known biology"
            ],
            "attributes": [
                {
                    "name": "Feasibility",
                    "rubric": "1 impossible .. 5 routine",
                }
            ],
        }
    }
    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(supervisor_guidance=guidance),
    )
    assert "testable within 2 years" in prompt
    assert "penalize ideas that restate known biology" in prompt
    assert "Feasibility" in prompt
    assert "1 impossible .. 5 routine" in prompt


# critical_criteria's richer {name, questions} shape (R12-23) is covered
# in test_prompts_review_critical_criteria.py (file-length ceiling).


def test_review_prompt_meta_review_branch() -> None:
    """Meta-review context surfaces common strengths/weaknesses in prompt."""
    meta_review = {
        "common_strengths": ["clear mechanism"],
        "common_weaknesses": ["weak controls"],
    }
    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(meta_review=meta_review),
    )
    assert "Meta-Review Context" in prompt
    assert "clear mechanism" in prompt
    assert "weak controls" in prompt


def test_review_batch_prompt_interpolates_goal_and_list() -> None:
    """The batch review prompt embeds the goal and the hypotheses list block."""
    prompt, schema = get_review_batch_prompt(
        research_goal="reduce tumor metastasis",
        hypotheses_list="1. block CXCR4\n2. inhibit MMP-9",
    )
    assert "reduce tumor metastasis" in prompt
    assert "block CXCR4" in prompt
    assert "inhibit MMP-9" in prompt
    assert "{{MISSING" not in prompt
    assert isinstance(schema, dict)


# --- get_meta_review_prompt ------------------------------------------------


def test_meta_review_prompt_interpolates_goal_and_reviews() -> None:
    """The meta-review prompt embeds the goal, reviews, and any instructions.

    Regression guard: ``get_meta_review_prompt`` now substitutes the
    ``instructions`` template variable, so a caller-supplied value lands in the
    prompt and no ``{{MISSING:instructions}}`` sentinel leaks through.
    """
    prompt, schema = get_meta_review_prompt(
        research_goal="characterise synaptic pruning",
        all_reviews="Review A: strong. Review B: weak controls.",
        instructions="focus on safety",
    )
    assert "characterise synaptic pruning" in prompt
    assert "Review A: strong" in prompt
    assert "focus on safety" in prompt
    assert "{{MISSING:instructions}}" not in prompt
    assert isinstance(schema, dict)


def test_meta_review_prompt_includes_preferences() -> None:
    """The published meta-review prompt carries "Preferences: {preferences}".

    meta-review-08-meta-review-generation.md has a dedicated Preferences
    slot, separate from "Additional instructions"; ours had no preferences
    placeholder at all, so the scientist's stated preferences never
    reached meta-review -- and, via _common.py's re-injection, never
    reached the six-plus downstream nodes that read meta_review either.
    """
    prompt, _ = get_meta_review_prompt(
        research_goal="g",
        all_reviews="r",
        preferences="prioritize wet-lab feasibility over novelty",
    )
    assert "prioritize wet-lab feasibility over novelty" in prompt
    assert "{{MISSING" not in prompt


def test_meta_review_prompt_defaults_preferences_when_absent() -> None:
    """Absent preferences fall back to the same default as generation's."""
    prompt, _ = get_meta_review_prompt(research_goal="g", all_reviews="r")
    assert "Focus on novelty, testability, and potential impact." in prompt


def test_meta_review_prompt_supervisor_guidance_branch() -> None:
    """Guidance adds key areas and evolution guidance to the meta-review."""
    with_guidance, _ = get_meta_review_prompt(
        research_goal="g",
        all_reviews="r",
        context=PromptRunContext(supervisor_guidance=_GUIDANCE),
    )
    assert "mitochondrial dysfunction" in with_guidance
    assert "Evolution Phase Guidance" in with_guidance


# --- get_proximity_prompt --------------------------------------------------


def test_proximity_prompt_encodes_dict_and_str_hypotheses() -> None:
    """Proximity JSON-encodes hypothesis texts from both dicts and strings."""
    prompt, schema = get_proximity_prompt(
        hypotheses=[
            {"text": "alpha pathway hypothesis"},
            "beta pathway hypothesis",
        ]
    )
    assert "alpha pathway hypothesis" in prompt
    assert "beta pathway hypothesis" in prompt
    assert "{{MISSING" not in prompt
    assert isinstance(schema, dict)


def test_proximity_prompt_guidance_branch() -> None:
    """Supervisor guidance adds a key-research-areas block to proximity."""
    prompt, _ = get_proximity_prompt(
        hypotheses=["h"], supervisor_guidance=_GUIDANCE
    )
    assert "oxidative stress" in prompt


# --- get_ranking_prompt ----------------------------------------------------


def test_ranking_prompt_interpolates_both_hypotheses() -> None:
    """The ranking prompt embeds the goal and both compared hypotheses."""
    prompt, schema = get_ranking_prompt(
        research_goal="optimise CRISPR delivery",
        side_a=RankingSide(text="lipid nanoparticle approach"),
        side_b=RankingSide(text="AAV vector approach"),
    )
    assert "optimise CRISPR delivery" in prompt
    assert "lipid nanoparticle approach" in prompt
    assert "AAV vector approach" in prompt
    assert "{{MISSING" not in prompt
    assert isinstance(schema, dict)


def test_ranking_prompt_review_scores_branch() -> None:
    """Review scores render inside that side's own published review slot."""
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(
            text="a", review={"overall_score": 8.5, "scores": {"novelty": 9}}
        ),
        side_b=RankingSide(text="b", review={"overall_score": 6.0}),
    )
    assert "Review of hypothesis 1:\nReview scores:" in prompt
    assert "8.5" in prompt
    assert "novelty" in prompt


def test_ranking_prompt_review_scores_says_disregard_not_consider() -> None:
    """The review-scores section instructs the judge per the published prompt.

    Published (ranking-04-pairwise-comparison.md): "Disregard these scores
    in your comparative analysis, as they may not be directly comparable
    across reviews." Ours used to say the opposite ("Consider these
    scores, but make your judgment based on comprehensive comparison, not
    just scores.").
    """
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(text="a", review={"overall_score": 8.5}),
        side_b=RankingSide(text="b", review={"overall_score": 6.0}),
    )
    assert (
        "Disregard these scores in your comparative analysis, as they may"
        " not be directly comparable across reviews." in prompt
    )
    assert "Consider these scores" not in prompt


def test_ranking_prompt_reflection_notes_default_when_absent() -> None:
    """Absent reflection notes fall back to the documented placeholder text."""
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(text="a"),
        side_b=RankingSide(text="b"),
    )
    assert "No reflection notes available." in prompt


def test_ranking_prompt_renders_mature_review_findings() -> None:
    """Mature-review verdicts reach the judge through the side summary."""
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(
            text="a",
            mature_reviews={
                "full": {
                    "verdict": "rejected",
                    "justification": "circular pathway",
                },
                "simulation": {
                    "verdict": "breaks_down",
                    "decisive_step": "binding fails",
                },
            },
        ),
        side_b=RankingSide(text="b"),
    )
    assert "Hypothesis 1 Mature Review Findings" in prompt
    assert "Full review verdict: rejected" in prompt
    assert "circular pathway" in prompt
    assert "Simulation review verdict: breaks_down" in prompt
    assert "Decisive step: binding fails" in prompt
    assert "Hypothesis 2 Mature Review Findings" not in prompt
    assert "{{MISSING" not in prompt


def test_ranking_prompt_has_no_mature_review_block_without_reviews() -> None:
    """Before the mature cascade the prompt renders no findings block."""
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(text="a"),
        side_b=RankingSide(text="b"),
    )
    assert "Mature Review Findings" not in prompt
    assert "{{MISSING" not in prompt


# --- domain injection ------------------------------------------------------


def test_domain_injection_populates_domain_placeholders() -> None:
    """A registry with prompts_config fills domain_* placeholders (review)."""

    class _StubPromptsConfig:
        domain_context = "ONCOLOGY-CONTEXT"
        generation_guidance = "GEN-G"
        review_guidance = "REVIEW-G"
        evolution_guidance = "EVO-G"
        reflection_guidance = "REFL-G"

    class _StubRegistry:
        def get_prompts_config(self) -> _StubPromptsConfig:
            return _StubPromptsConfig()

    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(tool_registry=_StubRegistry()),
    )
    assert "ONCOLOGY-CONTEXT" in prompt
    assert "REVIEW-G" in prompt


_COVERAGE_META_REVIEW = {
    "common_strengths": ["clear mechanism"],
    "common_weaknesses": ["weak controls"],
    "emerging_themes": ["UNIQUEMARKER-already-covered-kinase-inhibition"],
    "strategic_recommendations": ["broaden the cohort"],
    "potential_connections": [
        {
            "connection_type": "complementary_mechanism",
            "synthesis_opportunity": (
                "UNIQUEMARKER-open-direction-combine-autophagy-proteasome"
            ),
        }
    ],
}


def test_review_prompt_omits_coverage_sections() -> None:
    """The scored review prompt excludes the two novelty-adjacent sections.

    Deliberate scoping (see ``_format_meta_review_context``'s docstring):
    this prompt's score feeds the sticky, never-revisited initial review
    gate on its ``novelty`` axis, and "this area is already covered" /
    "this direction is open" read as direct novelty cues. The pre-
    existing strengths/weaknesses/recommendations sections are unaffected.
    """
    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(meta_review=_COVERAGE_META_REVIEW),
    )
    assert "Meta-Review Context" in prompt
    assert "clear mechanism" in prompt
    assert "weak controls" in prompt
    assert "broaden the cohort" in prompt
    assert "Research Areas Already Covered" not in prompt
    assert "Open Directions Flagged for Further Exploration" not in prompt
    assert "UNIQUEMARKER-already-covered-kinase-inhibition" not in prompt
    assert "UNIQUEMARKER-open-direction-combine-autophagy-proteasome" not in (
        prompt
    )


def test_review_batch_prompt_omits_coverage_sections() -> None:
    """The comparative batch review prompt excludes the same two sections."""
    prompt, _ = get_review_batch_prompt(
        research_goal="reduce tumor metastasis",
        hypotheses_list="1. block CXCR4\n2. inhibit MMP-9",
        context=PromptRunContext(meta_review=_COVERAGE_META_REVIEW),
    )
    assert "Meta-Review Context" in prompt
    assert "broaden the cohort" in prompt
    assert "Research Areas Already Covered" not in prompt
    assert "Open Directions Flagged for Further Exploration" not in prompt
    assert "UNIQUEMARKER-already-covered-kinase-inhibition" not in prompt
    assert "UNIQUEMARKER-open-direction-combine-autophagy-proteasome" not in (
        prompt
    )


def test_ranking_prompt_keeps_coverage_sections() -> None:
    """Contrast: the tournament judge keeps both sections by default.

    It is a reversible Elo signal, not a gate.
    """
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(text="A"),
        side_b=RankingSide(text="B"),
        context=PromptRunContext(meta_review=_COVERAGE_META_REVIEW),
    )
    assert "UNIQUEMARKER-already-covered-kinase-inhibition" in prompt
    assert "UNIQUEMARKER-open-direction-combine-autophagy-proteasome" in prompt


def test_review_prompt_critical_criteria_structured_shape() -> None:
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
    counts (6 criteria -- the union of the Evaluation Criteria and Review
    summary sections, R12-23b -- 4 questions each) regardless of what the
    model actually returned -- the same defense
    research_overview_directions.py applies for its own nested lists.
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
    assert "criterion 5" in prompt
    assert "criterion 6" not in prompt
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


def test_review_prompt_critical_criteria_not_a_list_degrades() -> None:
    """A malformed (non-list) critical_criteria field degrades, not crashes.

    ``_guidance_items`` wraps a bare string as a single-item list, so this
    still renders it as one legacy-shaped criterion rather than raising.
    """
    guidance = {
        "workflow_plan": {
            "review_phase": {"critical_criteria": "not a list"},
        }
    }
    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(supervisor_guidance=guidance),
    )
    assert "not a list" in prompt


def test_review_prompt_excludes_description_even_when_present() -> None:
    """R12-23b: ``description`` is deliberately report-only, never injected.

    ``description`` backs the report's own "Evaluation Criteria" section
    (``report/markdown/supervisor.py``) -- this call site runs per
    hypothesis, per review, and the prose states the same substance the
    questions already express operationally, so injecting it here would
    roughly double this per-hypothesis guidance block for no reviewer
    benefit (see planning.py's ``CRITICAL_CRITERIA_MAX_COUNT`` comment).
    This is the test that protects that design decision: the name and
    questions must still reach the reviewer, the description must not.
    """
    marker = "UNIQUE_DESCRIPTION_PROSE_MARKER_NEVER_INJECTED"
    guidance = {
        "workflow_plan": {
            "review_phase": {
                "critical_criteria": [
                    {
                        "name": "Kinetic Feasibility",
                        "description": (
                            f"{marker}: explains what this criterion"
                            " demands and why it matters for the goal."
                        ),
                        "questions": [
                            {
                                "name": "Kinetic Competition",
                                "question": "Does degradation outpace"
                                " synthesis?",
                            }
                        ],
                    }
                ],
            }
        }
    }
    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(supervisor_guidance=guidance),
    )
    assert "Kinetic Feasibility" in prompt
    assert "Kinetic Competition" in prompt
    assert "Does degradation outpace synthesis?" in prompt
    assert marker not in prompt


def test_review_prompt_blank_description_is_harmless() -> None:
    """A whitespace-only description doesn't affect prompt injection either.

    ``description`` is never read here regardless of its content, so a
    blank one behaves exactly like an absent one.
    """
    guidance = {
        "workflow_plan": {
            "review_phase": {
                "critical_criteria": [
                    {
                        "name": "Valid Criterion",
                        "description": "   ",
                        "questions": [{"question": "Q?"}],
                    }
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
    assert "Q?" in prompt


_TEMPLATES = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src"
    / "co_scientist"
    / "prompts"
    / "templates"
)


def _enum_values(node: Any, path: str = "") -> list[tuple[str, list[Any]]]:
    """Collects (property path, enum values) for every enum in a schema."""
    if not isinstance(node, dict):
        return []
    found: list[tuple[str, list[Any]]] = []
    if "enum" in node:
        found.append((path or "<root>", node["enum"]))
    for name, subschema in (node.get("properties") or {}).items():
        found += _enum_values(subschema, f"{path}.{name}" if path else name)
    if "items" in node:
        found += _enum_values(node["items"], path + "[]")
    return found


def test_prompts_name_the_enum_values_their_schema_accepts() -> None:
    unnamed: list[str] = []
    for prompt_name, schema in sorted(_PROMPT_SCHEMA_MAP.items()):
        template = _TEMPLATES / f"{prompt_name}.md"
        assert template.exists(), f"{prompt_name} has no template"
        text = template.read_text()
        for path, values in _enum_values(schema.get("schema", schema)):
            missing = [str(v) for v in values if str(v) not in text]
            if missing:
                unnamed.append(f"  {prompt_name}.md: {path} omits {missing}")
    assert not unnamed, "prompts that do not name their enum values:\n" + (
        "\n".join(unnamed)
    )


def test_ranking_prompt_names_every_comparison_field() -> None:
    """Both tournament prompts name the keys their judgment allows.

    judgment_explanation is closed, and its keys appeared nowhere but the
    schema block appended to the prompt -- the criteria the prompt itself
    lists are prose headings ("Novelty and originality"). A judge asked
    for comparisons in one vocabulary and given keys in another answered
    with a key of its own invention, which cost the match a second call.
    Both published ranking prompts answer against this one schema, so
    both must name every key.
    """
    explanation = RANKING_SCHEMA["schema"]["properties"]["judgment_explanation"]
    for name in ("ranking_pairwise", "ranking_debate"):
        template = (_TEMPLATES / f"{name}.md").read_text()
        for field in explanation["required"]:
            assert field in template, f"{name}.md does not name {field}"
