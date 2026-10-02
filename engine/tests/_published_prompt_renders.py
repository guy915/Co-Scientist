"""Drives the real prompt builders for every published prompt.

The mapping from published prompt to counterpart follows
``prompts/templates/README.md``. Where one published prompt maps to two
of ours, both are rendered; the first listed is the *primary*, the one
whose internal ordering the fidelity tests check.

The fixture lives in ``_published_prompt_fixtures.py`` so that one
populated research goal feeds every builder, and a builder is reached
only through its real public entry point.
"""

from __future__ import annotations

import json
import re

from co_scientist.agents.evolution import EvolutionContext
from co_scientist.agents.evolution.evolution_operators import (
    EvolutionOperator,
    operator_template,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _build_evolution_prompt,
    _EvolutionOperation,
)
from co_scientist.agents.ranking.ranking_debate_turns import (
    _build_matchup_prompt_from_ctx,
    _build_turn_prompt,
    _DebateContext,
)
from co_scientist.prompts import (
    get_meta_review_prompt,
    get_reflection_prompt,
)
from co_scientist.prompts.generation_debate import (
    DebatePromptRequest,
    get_debate_generation_prompt,
)
from co_scientist.prompts.generation_draft import (
    DraftPromptRequest,
    get_draft_prompt_with_tools,
)
from tests._published_prompt_fixtures import (
    ARTICLES_WITH_REASONING,
    ATTRIBUTES,
    CRITERIA,
    GOAL,
    HYPOTHESIS_TEXT,
    INSTRUCTIONS,
    META_REVIEW,
    PARTNER_TEXT,
    PREFERENCES,
    REFERENCE_LIST,
    SUPERVISOR_GUIDANCE,
    TRANSCRIPT,
    Counterpart,
    Rendered,
    ToolRegistry,
    articles,
    reviewed_hypothesis,
    run_context,
)


def _render_generation_01() -> Rendered:
    draft, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal=GOAL,
            hypotheses_count=4,
            articles=articles(),
            articles_with_reasoning=ARTICLES_WITH_REASONING,
            preferences=PREFERENCES,
            attributes=ATTRIBUTES,
            user_hypotheses=[HYPOTHESIS_TEXT],
            instructions=INSTRUCTIONS,
            reference_list=REFERENCE_LIST,
            research_expansion_section=(
                "## Research Expansion\nBroaden into biliary fibrosis.\n"
            ),
            falsified_assumptions_section=(
                "## Falsified Assumptions\nStellate quiescence is not"
                " reversible by diet alone.\n"
            ),
            lab_constraints=["No BSL-3 access", "Rodent models only"],
            skills_section="\n- `run_analysis`: execute a bundled skill.",
            context=run_context(),
        )
    )
    return Rendered(
        published="generation-01-hypothesis-after-literature-review",
        counterparts=(
            Counterpart(
                "generation_draft_with_tools",
                "prompts/generation_draft.py::get_draft_prompt_with_tools"
                " -> loading.py::_build_prompt"
                " -> templates/generation_draft_with_tools.md",
                draft,
            ),
            Counterpart(
                "generation_debate_and_literature",
                "prompts/generation_debate.py"
                "::get_debate_generation_prompt"
                " -> templates/generation_debate_and_literature.md",
                _debate_prompt(with_literature=True),
            ),
        ),
    )


def _debate_prompt(*, with_literature: bool) -> str:
    prompt, _ = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal=GOAL,
            transcript=TRANSCRIPT,
            preferences=PREFERENCES,
            attributes=ATTRIBUTES,
            user_hypotheses=[HYPOTHESIS_TEXT],
            instructions=INSTRUCTIONS,
            criteria=CRITERIA,
            is_final_turn=True,
            articles_with_reasoning=(
                ARTICLES_WITH_REASONING if with_literature else None
            ),
            articles=articles() if with_literature else None,
            reference_list=REFERENCE_LIST if with_literature else "",
            context=run_context(),
        )
    )
    return prompt


def _render_generation_02() -> Rendered:
    return Rendered(
        published="generation-02-hypothesis-after-scientific-debate",
        counterparts=(
            Counterpart(
                "generation_debate_and_literature",
                "prompts/generation_debate.py"
                "::get_debate_generation_prompt"
                " -> _render_debate_prompt"
                " -> templates/generation_debate_and_literature.md"
                " + _DEBATE_FINAL_TURN_INSTRUCTIONS",
                _debate_prompt(with_literature=True),
            ),
            Counterpart(
                "generation_after_debate",
                "prompts/generation_debate.py"
                "::get_debate_generation_prompt"
                " -> _render_debate_prompt"
                " -> templates/generation_after_debate.md"
                " + _DEBATE_FINAL_TURN_INSTRUCTIONS",
                _debate_prompt(with_literature=False),
            ),
        ),
    )


def _render_reflection_03() -> Rendered:
    prompt, _ = get_reflection_prompt(
        ARTICLES_WITH_REASONING,
        HYPOTHESIS_TEXT,
        indra_evidence=(
            "INDRA: TGFB1 activates ACTA2 expression (12 statements)."
        ),
        context=run_context(),
    )
    return Rendered(
        published="reflection-03-generate-observations",
        counterparts=(
            Counterpart(
                "reflection_observations",
                "prompts/review.py::get_reflection_prompt"
                " -> loading.py::_build_prompt"
                " -> templates/reflection_observations.md",
                prompt,
            ),
        ),
    )


def _debate_context() -> _DebateContext:
    return _DebateContext(
        hypothesis_a=reviewed_hypothesis(HYPOTHESIS_TEXT, "Hypothesis A"),
        hypothesis_b=reviewed_hypothesis(PARTNER_TEXT, "Hypothesis B"),
        research_goal=GOAL,
        model_name="offline/test-model",
        supervisor_guidance=SUPERVISOR_GUIDANCE,
        meta_review=META_REVIEW,
        tool_registry=ToolRegistry(),
        run_setup_guidance="This run targets a twelve-week pilot.",
        run_focus_guidance="Keep every proposal repurposing-first.",
        matchup_index=0,
        criteria=CRITERIA,
        preferences=PREFERENCES,
    )


def _render_ranking_04() -> Rendered:
    base = _build_matchup_prompt_from_ctx(_debate_context())
    return Rendered(
        published="ranking-04-pairwise-comparison",
        counterparts=(
            Counterpart(
                "ranking_single_shot",
                "agents/ranking/ranking_prompt.py::_build_matchup_prompt"
                " -> prompts/ranking.py::get_ranking_prompt"
                " (_format_ranking_preferences,"
                " _format_ranking_evaluation_criteria,"
                " _format_ranking_notes,"
                " ranking_sides.py::format_side_review)"
                " -> templates/ranking_pairwise.md",
                base.prompt,
            ),
        ),
    )


def _render_ranking_05() -> Rendered:
    # A top-ranked matchup: judge_matchup sets ``debate`` from the turn
    # budget, which is what routes the render onto ranking_debate.md.
    ctx = _debate_context()._replace(debate=True)
    base = _build_matchup_prompt_from_ctx(ctx)
    # Shaped exactly as ``ranking_debate._run_debate_turn`` records a turn:
    # ``winner`` is the canonical side and ``winner_id`` the Hypothesis
    # UUID. A hand-written ``winner_id: "A"`` used to hide that the
    # appended block printed the UUID at the judge.
    transcript = [
        {
            "turn": 1,
            "winner": "a",
            "winner_id": ctx.hypothesis_a.id,
            "reasoning": (
                "A specifies the pilot readout; B leaves the threshold"
                " unstated."
            ),
            "presentation_order": "ab",
            "valid_output": True,
        }
    ]
    turn = _build_turn_prompt(ctx, 1, False, base, transcript)
    return Rendered(
        published="ranking-05-comparison-via-scientific-debate",
        counterparts=(
            Counterpart(
                "ranking_debate_turn",
                "agents/ranking/ranking_debate_turns.py"
                "::_build_turn_prompt -> _append_debate_context"
                " (on a templates/ranking_debate.md render)",
                turn.prompt,
            ),
        ),
    )


def _evolution_context() -> EvolutionContext:
    from tests._state import make_state

    state = make_state(
        research_goal=GOAL,
        preferences=PREFERENCES,
        lab_constraints=["No BSL-3 access", "Rodent models only"],
    )
    return EvolutionContext(
        model_name="offline/test-model",
        meta_review=META_REVIEW,
        removed_duplicates=["An earlier duplicate of the parent idea."],
        creation_iteration=2,
        supervisor_guidance=SUPERVISOR_GUIDANCE,
        articles_with_reasoning=ARTICLES_WITH_REASONING,
        run_id="run-fixture",
        tool_registry=ToolRegistry(),
        run_setup_guidance="This run targets a twelve-week pilot.",
        run_focus_guidance="Keep every proposal repurposing-first.",
        state=state,
    )


def _evolution_prompt(operator: EvolutionOperator) -> str:
    parent = reviewed_hypothesis(HYPOTHESIS_TEXT, "Parent")
    partner = reviewed_hypothesis(PARTNER_TEXT, "Partner")
    prompt, _ = _build_evolution_prompt(
        parent,
        ["A distinct idea about biliary fibrogenesis."],
        _evolution_context(),
        _EvolutionOperation(
            operator=operator,
            specialist_feedback=json.dumps(
                {"ranking": "lost on feasibility"}, indent=2
            ),
            partners=(partner,),
        ),
        grounding_evidence=(
            "Targeted evidence: PRO-C3 tracks fibrogenesis in two"
            " independent cohorts [P1]."
        ),
    )
    return prompt


def _evolution_counterpart(
    operator: EvolutionOperator,
) -> Counterpart:
    return Counterpart(
        f"evolution_{operator.value}",
        "agents/evolution/evolve_prompt.py::_build_evolution_prompt"
        f" -> templates/{operator_template(operator)}.md"
        " (a published-prompt template renders whole, with the diversity"
        " guard as a slot; every other operator appends"
        " _format_operator_section + _format_diversity_instruction)",
        _evolution_prompt(operator),
    )


def _render_evolution_06() -> Rendered:
    return Rendered(
        published="evolution-06-feasibility-improvement",
        counterparts=(
            _evolution_counterpart(EvolutionOperator.COHERENCE_FEASIBILITY),
        ),
    )


def _render_evolution_07() -> Rendered:
    # One counterpart since MP-8 was resolved: OUT_OF_BOX both carries
    # A.7's name and receives its {hypotheses} input. INSPIRATION is the
    # paper's separately disclosed "inspiration from existing hypotheses"
    # strategy and has no published prompt of its own.
    return Rendered(
        published="evolution-07-out-of-the-box-thinking",
        counterparts=(_evolution_counterpart(EvolutionOperator.OUT_OF_BOX),),
    )


def _render_meta_review_08() -> Rendered:
    prompt, _ = get_meta_review_prompt(
        research_goal=GOAL,
        all_reviews=json.dumps(
            [
                {
                    "hypothesis_index": 1,
                    "review_summary": "Strong mechanism, weak pilot.",
                    "scores": {"novelty": 8, "feasibility": 5},
                }
            ],
            indent=2,
        ),
        instructions=INSTRUCTIONS,
        preferences=PREFERENCES,
        context=run_context(),
    )
    return Rendered(
        published="meta-review-08-meta-review-generation",
        counterparts=(
            Counterpart(
                "meta_review",
                "prompts/planning.py::get_meta_review_prompt"
                " -> loading.py::_build_prompt"
                " -> templates/meta_review.md",
                prompt,
            ),
        ),
    )


_RENDERERS = (
    _render_generation_01,
    _render_generation_02,
    _render_reflection_03,
    _render_ranking_04,
    _render_ranking_05,
    _render_evolution_06,
    _render_evolution_07,
    _render_meta_review_08,
)


def render_all() -> dict[str, Rendered]:
    """Render every published prompt's counterpart(s), keyed by stem."""
    rendered = [render() for render in _RENDERERS]
    return {item.published: item for item in rendered}


def unrendered_slots(text: str) -> list[str]:
    """Return every leftover template marker in a rendered prompt."""
    return re.findall(r"\{\{[^}]*\}\}", text)
