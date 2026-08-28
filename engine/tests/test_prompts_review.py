"""Tests for the planning/evaluation prompt builders in ``co_scientist``.

Covers the pure template helpers (``substitute_variables``,
``load_prompt_with_schema``, ``_get_domain_variables``) and the supervisor,
review, meta-review, proximity, and ranking prompt builders. The generation and
literature-review prompt builders are covered in ``test_prompts_generation``.

These functions are pure template builders: each reads a markdown template,
substitutes ``{{variable}}`` placeholders with the caller's inputs, and returns
either a prompt string or a ``(prompt, schema)`` tuple. The tests assert that
the returned prompt is a non-empty ``str`` that interpolates the key inputs,
that schemas have the right shape, and that a few conditional branches change
the output.

``substitute_variables`` replaces any template placeholder the builder does not
supply with a literal ``{{MISSING:<name>}}`` sentinel rather than raising. The
builders leave no sentinels behind, so their tests assert ``"{{MISSING" not in
prompt`` to verify *full* interpolation.

The builders perform no LLM or network calls, so the tests are deterministic
with no mocking. Domain-variable injection (``_get_domain_variables``) falls
back to empty strings when no tool registry config is available, so prompts are
exercised in their plain (domain-agnostic) form.
"""

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
    """Providing review scores adds a review-scores context section."""
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(
            text="a", review={"overall_score": 8.5, "scores": {"novelty": 9}}
        ),
        side_b=RankingSide(text="b", review={"overall_score": 6.0}),
    )
    assert "Review Scores Context" in prompt
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
    assert "Hypothesis A Mature Review Findings" in prompt
    assert "Full review verdict: rejected" in prompt
    assert "circular pathway" in prompt
    assert "Simulation review verdict: breaks_down" in prompt
    assert "Decisive step: binding fails" in prompt
    assert "Hypothesis B Mature Review Findings" not in prompt
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
