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


def test_substitute_variables_replaces_placeholder() -> None:
    assert substitute_variables("Hello {{name}}", {"name": "World"}) == (
        "Hello World"
    )


def test_substitute_variables_coerces_non_string_values() -> None:
    assert substitute_variables("count={{n}}", {"n": 7}) == "count=7"


def test_substitute_variables_missing_key_emits_marker() -> None:
    out = substitute_variables("a {{absent}} b", {})
    assert "{{MISSING:absent}}" in out


def test_load_prompt_with_schema_returns_prompt_and_schema() -> None:
    """This low-level loader leaves unsupplied placeholders unfilled."""
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
    _, schema = load_prompt_with_schema("literature_review_synthesis", {})
    assert schema is None


def test_get_domain_variables_none_returns_string_dict() -> None:
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


def test_supervisor_prompt_interpolates_goal_and_counts() -> None:
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


def test_review_prompt_interpolates_goal_and_hypothesis() -> None:
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


def test_review_prompt_meta_review_branch() -> None:
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
    prompt, schema = get_review_batch_prompt(
        research_goal="reduce tumor metastasis",
        hypotheses_list="1. block CXCR4\n2. inhibit MMP-9",
    )
    assert "reduce tumor metastasis" in prompt
    assert "block CXCR4" in prompt
    assert "inhibit MMP-9" in prompt
    assert "{{MISSING" not in prompt
    assert isinstance(schema, dict)


def test_meta_review_prompt_interpolates_goal_and_reviews() -> None:
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
    prompt, _ = get_meta_review_prompt(
        research_goal="g",
        all_reviews="r",
        preferences="prioritize wet-lab feasibility over novelty",
    )
    assert "prioritize wet-lab feasibility over novelty" in prompt
    assert "{{MISSING" not in prompt


def test_meta_review_prompt_defaults_preferences_when_absent() -> None:
    prompt, _ = get_meta_review_prompt(research_goal="g", all_reviews="r")
    assert "Focus on novelty, testability, and potential impact." in prompt


def test_meta_review_prompt_supervisor_guidance_branch() -> None:
    with_guidance, _ = get_meta_review_prompt(
        research_goal="g",
        all_reviews="r",
        context=PromptRunContext(supervisor_guidance=_GUIDANCE),
    )
    assert "mitochondrial dysfunction" in with_guidance
    assert "Evolution Phase Guidance" in with_guidance


def test_proximity_prompt_encodes_dict_and_str_hypotheses() -> None:
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
    prompt, _ = get_proximity_prompt(
        hypotheses=["h"], supervisor_guidance=_GUIDANCE
    )
    assert "oxidative stress" in prompt


def test_ranking_prompt_interpolates_both_hypotheses() -> None:
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
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(text="a"),
        side_b=RankingSide(text="b"),
    )
    assert "No reflection notes available." in prompt


def test_ranking_prompt_renders_mature_review_findings() -> None:
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
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(text="a"),
        side_b=RankingSide(text="b"),
    )
    assert "Mature Review Findings" not in prompt
    assert "{{MISSING" not in prompt


def test_domain_injection_populates_domain_placeholders() -> None:

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
    """Coverage cues can bias the sticky initial novelty gate."""
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
    """The json_object downgrade does not enforce maxItems server-side."""
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
    """Descriptions are report-only; injecting them duplicates per-review
    guidance."""
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
    """Prose/schema vocabulary disagreement costs the judge another call."""
    explanation = RANKING_SCHEMA["schema"]["properties"]["judgment_explanation"]
    for name in ("ranking_pairwise", "ranking_debate"):
        template = (_TEMPLATES / f"{name}.md").read_text()
        for field in explanation["required"]:
            assert field in template, f"{name}.md does not name {field}"
