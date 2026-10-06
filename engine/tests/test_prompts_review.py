from __future__ import annotations

import pathlib
from typing import Any

from co_scientist.prompts import (
    PromptRunContext,
    RankingSide,
    SupervisorPromptInputs,
    get_meta_review_prompt,
    get_ranking_prompt,
    get_review_prompt,
    get_supervisor_prompt,
    substitute_variables,
)
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


def test_substitute_variables_missing_key_emits_marker() -> None:
    out = substitute_variables("a {{absent}} b", {})
    assert "{{MISSING:absent}}" in out


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


def test_meta_review_prompt_includes_preferences() -> None:
    prompt, _ = get_meta_review_prompt(
        research_goal="g",
        all_reviews="r",
        preferences="prioritize wet-lab feasibility over novelty",
    )
    assert "prioritize wet-lab feasibility over novelty" in prompt
    assert "{{MISSING" not in prompt


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


def test_ranking_prompt_keeps_coverage_sections() -> None:
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(text="A"),
        side_b=RankingSide(text="B"),
        context=PromptRunContext(meta_review=_COVERAGE_META_REVIEW),
    )
    assert "UNIQUEMARKER-already-covered-kinase-inhibition" in prompt
    assert "UNIQUEMARKER-open-direction-combine-autophagy-proteasome" in prompt


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
