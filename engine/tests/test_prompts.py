"""Tests for the prompt builders in ``co_scientist.prompts``.

These functions are pure template builders: each reads a markdown template,
substitutes ``{{variable}}`` placeholders with the caller's inputs, and returns
either a prompt string or a ``(prompt, schema)`` tuple. The tests assert that
the returned prompt is a non-empty ``str`` that actually interpolates the key
inputs (research goal, hypothesis text, counts, etc.), that schemas have the
right shape, and that a few conditional branches change the output.

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

from co_scientist.prompts import _get_domain_variables
from co_scientist.prompts import format_articles_metadata
from co_scientist.prompts import get_debate_generation_prompt
from co_scientist.prompts import get_deep_verification_prompt
from co_scientist.prompts import get_draft_prompt_with_tools
from co_scientist.prompts import (get_literature_review_paper_analysis_prompt)
from co_scientist.prompts import (
    get_literature_review_query_generation_pubmed_prompt)
from co_scientist.prompts import get_meta_review_prompt
from co_scientist.prompts import get_proximity_prompt
from co_scientist.prompts import get_ranking_prompt
from co_scientist.prompts import get_reflection_prompt
from co_scientist.prompts import get_research_overview_prompt
from co_scientist.prompts import get_review_batch_prompt
from co_scientist.prompts import get_review_prompt
from co_scientist.prompts import get_supervisor_prompt
from co_scientist.prompts import load_prompt_with_schema
from co_scientist.prompts import substitute_variables
from tests._state import make_article

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
    assert substitute_variables("Hello {{name}}",
                                {"name": "World"}) == ("Hello World")


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
    prompt, schema = load_prompt_with_schema("review", {
        "research_goal": "cure ALS",
        "hypothesis_text": "TDP-43 aggregation",
    })
    assert isinstance(prompt, str)
    assert prompt
    assert "cure ALS" in prompt
    assert isinstance(schema, dict)


def test_load_prompt_with_schema_none_for_unschemaed_prompt() -> None:
    """A prompt with no registered schema returns ``None`` for the schema."""
    _, schema = load_prompt_with_schema("literature_review_synthesis", {})
    assert schema is None


def test_get_domain_variables_none_returns_string_dict() -> None:
    """``_get_domain_variables(None)`` returns the expected keys, all strings."""
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
        research_goal="map gut-brain axis signaling",
        initial_hypotheses_count=4,
        max_iterations=3,
        evolution_max_count=6,
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
        research_goal="goal",
        constraints=["budget under 10k", "in-vitro only"],
    )
    without_constraints, _ = get_supervisor_prompt(research_goal="goal")
    assert "budget under 10k" in with_constraints
    assert "budget under 10k" not in without_constraints
    assert "None provided" in without_constraints


def test_supervisor_prompt_pubmed_availability_branch() -> None:
    """PubMed/MCP availability flips the literature-review description text."""
    available, _ = get_supervisor_prompt(research_goal="g",
                                         pubmed_available=True)
    unavailable, _ = get_supervisor_prompt(research_goal="g",
                                           pubmed_available=False,
                                           mcp_available=False)
    assert "search pubmed" in available.lower()
    assert "not available" in unavailable.lower()


def test_prompt_builders_include_run_setup_guidance() -> None:
    """Durable setup guidance is embedded in node prompts."""
    setup_guidance = "Run setup:\n- Requirements:\n  - Focus on primary data"
    focus_guidance = "Prefer novelty while preserving testability."
    prompt, _ = get_supervisor_prompt(
        research_goal="g",
        run_setup_guidance=setup_guidance,
        run_focus_guidance=focus_guidance,
        criteria=["Causal clarity"],
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
    without_guidance, _ = get_review_prompt(research_goal="g",
                                            hypothesis_text="h")
    with_guidance, _ = get_review_prompt(research_goal="g",
                                         hypothesis_text="h",
                                         supervisor_guidance=_GUIDANCE)
    assert len(with_guidance) > len(without_guidance)
    assert "Supervisor Guidance for Review" in with_guidance
    assert "testability" in with_guidance


def test_review_prompt_meta_review_branch() -> None:
    """Meta-review context surfaces common strengths/weaknesses in the prompt."""
    meta_review = {
        "common_strengths": ["clear mechanism"],
        "common_weaknesses": ["weak controls"],
    }
    prompt, _ = get_review_prompt(research_goal="g",
                                  hypothesis_text="h",
                                  meta_review=meta_review)
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
    with_guidance, _ = get_meta_review_prompt(research_goal="g",
                                              all_reviews="r",
                                              supervisor_guidance=_GUIDANCE)
    assert "mitochondrial dysfunction" in with_guidance
    assert "Evolution Phase Guidance" in with_guidance


# --- get_proximity_prompt --------------------------------------------------


def test_proximity_prompt_encodes_dict_and_str_hypotheses() -> None:
    """Proximity JSON-encodes hypothesis texts from both dicts and strings."""
    prompt, schema = get_proximity_prompt(hypotheses=[
        {
            "text": "alpha pathway hypothesis"
        },
        "beta pathway hypothesis",
    ])
    assert "alpha pathway hypothesis" in prompt
    assert "beta pathway hypothesis" in prompt
    assert "{{MISSING" not in prompt
    assert isinstance(schema, dict)


def test_proximity_prompt_guidance_branch() -> None:
    """Supervisor guidance adds a key-research-areas block to proximity."""
    prompt, _ = get_proximity_prompt(hypotheses=["h"],
                                     supervisor_guidance=_GUIDANCE)
    assert "oxidative stress" in prompt


# --- get_ranking_prompt ----------------------------------------------------


def test_ranking_prompt_interpolates_both_hypotheses() -> None:
    """The ranking prompt embeds the goal and both compared hypotheses."""
    prompt, schema = get_ranking_prompt(
        research_goal="optimise CRISPR delivery",
        hypothesis_a="lipid nanoparticle approach",
        hypothesis_b="AAV vector approach",
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
        hypothesis_a="a",
        hypothesis_b="b",
        review_a={
            "overall_score": 8.5,
            "scores": {
                "novelty": 9
            }
        },
        review_b={"overall_score": 6.0},
    )
    assert "Review Scores Context" in prompt
    assert "8.5" in prompt
    assert "novelty" in prompt


def test_ranking_prompt_reflection_notes_default_when_absent() -> None:
    """Absent reflection notes fall back to the documented placeholder text."""
    prompt, _ = get_ranking_prompt(research_goal="g",
                                   hypothesis_a="a",
                                   hypothesis_b="b")
    assert "No reflection notes available." in prompt


# --- get_debate_generation_prompt ------------------------------------------


def test_debate_generation_non_final_turn_has_no_schema() -> None:
    """A non-final debate turn returns a conversational prompt, schema None."""
    prompt, schema = get_debate_generation_prompt(
        research_goal="design a self-healing polymer",
        hypotheses_count=3,
        transcript="Expert 1: ... Expert 2: ...",
        is_final_turn=False,
    )
    assert isinstance(prompt, str)
    assert "design a self-healing polymer" in prompt
    assert "Expert 1:" in prompt
    assert "{{MISSING" not in prompt
    assert schema is None


def test_debate_generation_final_turn_appends_json_block_and_schema() -> None:
    """The final turn appends JSON output instructions and returns a schema."""
    prompt, schema = get_debate_generation_prompt(
        research_goal="design a self-healing polymer",
        hypotheses_count=1,
        transcript="prior discussion",
        is_final_turn=True,
    )
    assert "FINAL TURN" in prompt
    assert "literature_grounding" in prompt
    assert "{{MISSING" not in prompt
    assert isinstance(schema, dict)


# --- get_draft_prompt_with_tools -------------------------------------------


def test_draft_prompt_with_tools_interpolates_goal_count_articles() -> None:
    """The draft-with-tools prompt embeds goal, count, and article metadata."""
    article = make_article(
        title="A landmark paper on neuroinflammation",
        authors=["A. Researcher"],
        year=2022,
        used_in_analysis=True,
    )
    prompt, schema = get_draft_prompt_with_tools(
        research_goal="map neuroinflammatory cascades",
        hypotheses_count=4,
        articles=[article],
    )
    assert "map neuroinflammatory cascades" in prompt
    assert "4" in prompt
    assert "A landmark paper on neuroinflammation" in prompt
    assert "{{MISSING" not in prompt
    assert isinstance(schema, dict)


# --- get_reflection_prompt -------------------------------------------------


def test_reflection_prompt_interpolates_hypothesis_and_evidence() -> None:
    """The reflection prompt embeds the hypothesis, summary, and KG evidence."""
    prompt, schema = get_reflection_prompt(
        articles_with_reasoning="Summary: APOE4 increases risk.",
        hypothesis_text="APOE4 impairs lipid transport in astrocytes",
        indra_evidence="APOE4 -> lipid dysregulation (12 papers)",
    )
    assert "Summary: APOE4 increases risk." in prompt
    assert "APOE4 impairs lipid transport in astrocytes" in prompt
    assert "APOE4 -> lipid dysregulation (12 papers)" in prompt
    assert "{{MISSING" not in prompt
    assert isinstance(schema, dict)


# --- format_articles_metadata ----------------------------------------------


def test_format_articles_metadata_renders_used_articles() -> None:
    """Used articles are rendered with title, authors, and year."""
    article = make_article(
        title="Targeting senescent cells",
        authors=["J. Doe", "K. Smith"],
        year=2021,
        citations=42,
        used_in_analysis=True,
    )
    out = format_articles_metadata([article])
    assert "Targeting senescent cells" in out
    assert "J. Doe" in out
    assert "2021" in out


def test_format_articles_metadata_empty_when_none_used() -> None:
    """An empty list, or articles not used in analysis, yields an empty str."""
    assert format_articles_metadata([]) == ""
    unused = make_article(title="Unused", used_in_analysis=False)
    assert format_articles_metadata([unused]) == ""


# --- literature query / paper analysis builders ----------------------------


def test_pubmed_query_prompt_interpolates_goal_and_lists() -> None:
    """The PubMed query prompt embeds the goal and provided literature."""
    prompt = get_literature_review_query_generation_pubmed_prompt(
        research_goal="find biomarkers for sepsis",
        user_literature=["Smith 2020 sepsis review"],
    )
    assert isinstance(prompt, str)
    assert "find biomarkers for sepsis" in prompt
    assert "Smith 2020 sepsis review" in prompt
    assert "{{MISSING" not in prompt


def test_paper_analysis_prompt_interpolates_metadata() -> None:
    """The paper-analysis prompt embeds the goal, title, authors, and year."""
    prompt = get_literature_review_paper_analysis_prompt(
        research_goal="explain insulin resistance",
        title="Hepatic glucose output revisited",
        authors=["P. First", "Q. Second"],
        year=2019,
        fulltext="Full text body discussing gluconeogenesis.",
    )
    assert "explain insulin resistance" in prompt
    assert "Hepatic glucose output revisited" in prompt
    assert "P. First" in prompt
    assert "2019" in prompt
    assert "Full text body discussing gluconeogenesis." in prompt
    # Every placeholder this builder owns is filled. (A blanket "{{MISSING"
    # check is not used here: the template embeds a literal ``{{...}}`` JSON
    # example block that ``substitute_variables`` mis-reads as a placeholder,
    # which is a template-escaping quirk independent of the builder's inputs.)
    for var in ("research_goal", "title", "authors", "year", "fulltext"):
        assert f"{{{{MISSING:{var}}}}}" not in prompt


def test_get_deep_verification_prompt_substitutes_and_returns_schema() -> None:
    """The deep-verification prompt embeds the goal and hypothesis text."""
    prompt, schema = get_deep_verification_prompt(
        research_goal="Repurpose a drug for AML",
        hypothesis_text="Reparixin inhibits CXCR1/2 in AML")
    assert "Reparixin inhibits CXCR1/2 in AML" in prompt
    assert "Repurpose a drug for AML" in prompt
    assert schema is not None
    assert "{hypothesis_text}" not in prompt  # placeholder fully substituted


def test_get_research_overview_prompt_substitutes_and_returns_schema() -> None:
    """The research-overview prompt embeds the goal and hypotheses summary."""
    prompt, schema = get_research_overview_prompt(
        research_goal="Find liver-fibrosis targets",
        hypotheses_summary="1. HDAC inhibition (Elo 1700)\n2. BRD4 (Elo 1650)")
    assert "Find liver-fibrosis targets" in prompt
    assert "HDAC inhibition" in prompt
    assert schema is not None
