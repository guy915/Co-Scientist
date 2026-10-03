"""Shared test fixtures for published corpus."""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pytest

from co_scientist.agents.evolution import EvolutionContext
from co_scientist.agents.evolution.evolve_prompt import (
    EvolutionOperator,
    _build_evolution_prompt,
    _EvolutionOperation,
    operator_template,
)
from co_scientist.agents.ranking.ranking_debate import (
    _build_matchup_prompt_from_ctx,
    _build_turn_prompt,
    _DebateContext,
)
from co_scientist.prompts import (
    PromptRunContext,
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
from tests._state import make_article, make_hypothesis, make_review

_APPENDIX = (
    Path(__file__).resolve().parents[2] / "docs" / "CORPUS-EXTRACTION.md"
)

# An Appendix-A prompt entry opens ``#### `<stem>.md` `` and wraps the
# verbatim reference file (comment header, ``# heading``, and the inner
# ```` ``` ```` prompt fence) in an outer fence of four-or-more backticks.
_OUTER_FENCE = re.compile(r"^(`{4,})\s*$")


def corpus_available() -> bool:
    """True when the published-prompt corpus is checked out beside the engine.

    Callers that read the corpus at *collection* time need this: a
    ``pytest.skip`` raised while a parametrization is being built is a
    collection error, not a skip, so the engine-alone checkout this module
    exists to tolerate would go red instead of quiet.

    Returns:
        Whether ``docs/CORPUS-EXTRACTION.md`` is present.
    """
    return _APPENDIX.is_file()


def published_prompt(name: str) -> str:
    """Return one of the eight prompts the papers publish in full.

    Reads the verbatim reference file as reproduced in ``docs/
    CORPUS-EXTRACTION.md``'s Appendix A -- the outer-fenced block under the
    ``#### `<stem>.md` `` heading -- so the returned text is the same
    header-comment-plus-fenced-body shape the standalone file carried.

    Args:
        name: The prompt's stem, e.g. ``ranking-04-pairwise-comparison``.

    Returns:
        The file's text, header comment and inner fence included.
    """
    if not _APPENDIX.is_file():
        pytest.skip("engine checked out without docs/CORPUS-EXTRACTION.md")
    lines = _APPENDIX.read_text(encoding="utf-8").splitlines()
    heading = f"#### `{name}.md`"
    return _extract_outer_fence(lines, heading, name)


def _extract_outer_fence(lines: list[str], heading: str, name: str) -> str:
    """Return the outer-fenced block that follows ``heading``.

    Args:
        lines: The Appendix file split into lines.
        heading: The ``#### `<stem>.md` `` line that opens the entry.
        name: The stem, for the assertion message.

    Returns:
        The block's inner text (the verbatim reference file).
    """
    start = next((i for i, ln in enumerate(lines) if ln.strip() == heading), -1)
    assert start >= 0, f"published prompt missing from Appendix A: {name}"
    fence = ""
    body: list[str] = []
    for line in lines[start + 1 :]:
        if not fence:
            if match := _OUTER_FENCE.match(line):
                fence = match.group(1)
            continue
        if line.strip() == fence:
            return "\n".join(body)
        body.append(line)
    raise AssertionError(f"published prompt has no closed fence: {name}")


GOAL = (
    "Identify a repurposable approved drug that suppresses hepatic"
    " fibrosis progression in patients with metabolic dysfunction-"
    "associated steatohepatitis."
)

PREFERENCES = (
    "Prefer mechanisms testable in a 12-week rodent model, with an"
    " approved compound and a measurable serum readout."
)

CRITERIA = [
    "Mechanistic specificity over correlative association",
    "Feasibility within a single academic laboratory",
    "Falsifiable within twelve weeks",
]

INSTRUCTIONS = (
    "Prioritise mechanisms with an existing clinical safety record and"
    " state the pilot readout that would settle each proposal."
)

ATTRIBUTES = ["novel", "testable", "mechanistically specific"]

ARTICLES_WITH_REASONING = (
    "Analysis 1 (2024, Hepatology): TGF-beta1 driven myofibroblast"
    " activation remains the dominant fibrogenic axis; the authors note"
    " that integrin alpha-v beta-6 blockade was never tested alongside"
    " an approved antifibrotic. Reasoning: this is an unexplored"
    " combination.\n"
    "Analysis 2 (2023, J Hepatol): pirfenidone reduced collagen"
    " deposition in a murine CCl4 model but was not evaluated in a"
    " steatohepatitis background. Reasoning: the model gap is the"
    " opening."
)

TRANSCRIPT = (
    "Expert 1: I propose integrin alpha-v beta-6 blockade combined with"
    " a low-dose approved antifibrotic.\n"
    "Expert 2: The combination is plausible, but the readout must"
    " separate lipotoxic injury from fibrogenesis."
)

HYPOTHESIS_TEXT = (
    "Low-dose pirfenidone combined with integrin alpha-v beta-6"
    " blockade suppresses hepatic myofibroblast activation in a"
    " steatohepatitis background, lowering serum PRO-C3 by at least"
    " thirty percent at twelve weeks."
)

PARTNER_TEXT = (
    "Selective ASK1 inhibition reduces hepatocyte apoptosis and"
    " secondarily lowers stellate-cell activation."
)

REFERENCE_LIST = (
    "[P1] Integrin alpha-v beta-6 in liver fibrosis (2024)\n"
    "[P2] Pirfenidone in experimental steatohepatitis (2023)"
)


@dataclasses.dataclass(frozen=True)
class _PromptsConfig:
    """Stands in for the tools-config domain block."""

    domain_context: str = (
        "You work in translational hepatology; assume access to rodent"
        " models and standard serum assays."
    )
    generation_guidance: str = (
        "Favour mechanisms with an approved compound already available."
    )
    review_guidance: str = (
        "Weigh translational plausibility alongside mechanistic novelty."
    )
    evolution_guidance: str = (
        "Refinements should stay implementable in an academic laboratory."
    )
    reflection_guidance: str = (
        "Treat rodent-only evidence as suggestive, not established."
    )


class ToolRegistry:
    """The shipped tool registry with the domain slots populated.

    Tool instructions come from the real default config, so the rendered
    prompt carries the tool block a production run would see; only the
    ``domain_*`` slots are overridden, because the shipped config leaves
    them empty and an empty slot would be indistinguishable from a
    missing published sentence.
    """

    def __init__(self) -> None:
        from co_scientist.config import get_tool_registry

        self._registry = get_tool_registry()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._registry, name)

    def get_prompts_config(self) -> _PromptsConfig:
        return _PromptsConfig()


SUPERVISOR_GUIDANCE: dict[str, Any] = {
    "research_goal_analysis": {
        "key_areas": [
            "myofibroblast activation",
            "drug repurposing safety record",
        ]
    },
    "workflow_plan": {
        "generation_phase": {
            "focus_areas": ["approved antifibrotics"],
            "diversity_requirements": ["one non-hepatic analogy"],
        },
        "evolution_phase": {
            "refinement_priorities": ["tighten the pilot readout"],
            "iteration_strategy": "deepen the two leading mechanisms",
        },
    },
}

META_REVIEW: dict[str, Any] = {
    "common_strengths": ["clear mechanistic framing"],
    "common_weaknesses": ["pilot thresholds are frequently unstated"],
    "strategic_recommendations": [
        "state a quantitative Go/No-Go for every proposal"
    ],
    "emerging_themes": ["integrin-directed antifibrotic combinations"],
    "covered_areas": ["stellate-cell biology"],
    "open_directions": ["biliary contributions to fibrogenesis"],
}


def run_context() -> PromptRunContext:
    return PromptRunContext(
        supervisor_guidance=SUPERVISOR_GUIDANCE,
        meta_review=META_REVIEW,
        tool_registry=ToolRegistry(),
        run_setup_guidance="This run targets a twelve-week pilot.",
        run_focus_guidance="Keep every proposal repurposing-first.",
        preferences=PREFERENCES,
    )


def articles() -> list[Any]:
    return [
        make_article(
            title="Integrin alpha-v beta-6 in liver fibrosis",
            authors=["Okada", "Ruiz"],
            year=2024,
            source_id="P1",
            used_in_analysis=True,
        ),
        make_article(
            title="Pirfenidone in experimental steatohepatitis",
            authors=["Delacroix"],
            year=2023,
            source_id="P2",
            used_in_analysis=True,
        ),
    ]


def reviewed_hypothesis(text: str, label: str) -> Any:
    """Build a hypothesis carrying every signal ranking can surface."""
    hypothesis = make_hypothesis(
        text=text,
        title=f"{label} mechanism",
        reviews=[make_review()],
        reflection_notes=(
            f"Classification: missing piece. {label} explains the"
            " unexplained PRO-C3 plateau reported in the 2024 cohort."
        ),
        deep_verification_probes=[
            {
                "question": (
                    "Does integrin blockade reach hepatic stellate"
                    " cells at tolerated doses?"
                ),
                "answer": "Yes in rodents; human exposure is untested.",
                "reasoning": "Rodent PK covers the target compartment.",
                "assumption_is_fundamental": True,
            }
        ],
        deep_verification_verdict="holds",
    )
    hypothesis.enrichments["full"] = {
        "verdict": "accepted",
        "justification": (
            f"{label}'s causal chain survives the literature check."
        ),
    }
    hypothesis.enrichments["simulation"] = {
        "verdict": "holds",
        "decisive_step": "stellate-cell deactivation at week six",
        "failure_points": ["off-target integrin engagement"],
    }
    return hypothesis


@dataclasses.dataclass(frozen=True)
class Counterpart:
    """One rendered prompt of ours that claims a published source."""

    name: str
    builder_chain: str
    text: str


@dataclasses.dataclass(frozen=True)
class Rendered:
    """Every counterpart of one published prompt.

    ``primary`` is the counterpart whose internal ordering the fidelity
    tests check; ``union`` is every counterpart's text concatenated, which
    is what a presence check runs against when the README maps one
    published prompt onto two of ours.
    """

    published: str
    counterparts: tuple[Counterpart, ...]

    @property
    def primary(self) -> Counterpart:
        return self.counterparts[0]

    @property
    def union(self) -> str:
        return "\n".join(part.text for part in self.counterparts)


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
                "agents/ranking/ranking_debate_turns.py::_build_matchup_prompt"
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
