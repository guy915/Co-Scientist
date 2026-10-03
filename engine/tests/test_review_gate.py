"""Offline contracts for review gate."""

from __future__ import annotations

import pathlib
from typing import Any

import jsonschema
import pytest

from co_scientist.agents.reflection.review import review_node
from co_scientist.agents.reflection.review_gate import (
    ReviewType,
    _apply_initial_review_gate,
    _gate_axes_for_criteria,
    derive_review_disposition,
    prompt_name_for,
    refresh_review_dispositions,
    reviews_needed,
    schema_for,
)
from co_scientist.agents.supervisor.orchestrator import (
    _compute_stats,
    _default_budget,
)
from co_scientist.constants import NEEDS_REVISION_SCORE, NOT_VIABLE_SCORE
from co_scientist.models import (
    SCIENTIST_REVIEWER,
    Hypothesis,
    HypothesisReview,
    has_peer_review,
)
from co_scientist.prompts.loading import load_prompt_with_schema
from co_scientist.scheduling.models import TaskType
from co_scientist.scheduling.policy import required_transition
from co_scientist.schemas.review import FULL_REVIEW_SCHEMA
from co_scientist.state import WorkflowState
from tests._state import make_hypothesis, make_state


def _review_with_scores(scores: dict[str, int]) -> HypothesisReview:
    """Build a review carrying the given per-axis scores."""
    return HypothesisReview(
        review_summary="summary",
        scores=scores,
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="feedback",
        overall_score=5,
    )


def test_absent_criteria_keep_the_default_soundness_novelty_gate() -> None:
    """Without criteria the gate consults exactly the historical axes."""
    assert _gate_axes_for_criteria(None) == (
        "scientific_soundness",
        "novelty",
    )
    assert _gate_axes_for_criteria([]) == ("scientific_soundness", "novelty")


def test_unmapped_criteria_fall_back_to_the_default_axes() -> None:
    """Criteria matching no scored axis gate like no criteria at all."""
    axes = _gate_axes_for_criteria(["purely aesthetic presentation"])
    assert axes == ("scientific_soundness", "novelty")


def test_criteria_resolve_onto_the_matching_scored_axes() -> None:
    """Each criterion maps onto its axes; duplicates gate once."""
    axes = _gate_axes_for_criteria(
        [
            "Scientific soundness",
            "Novelty over known mechanisms",
            "Discriminating experimental design",
            "Translational feasibility",
        ]
    )
    assert axes == (
        "scientific_soundness",
        "novelty",
        "testability",
        "potential_impact",
    )


def test_the_apps_published_default_criteria_resolve_onto_axes() -> None:
    """R12-4: the app's rendered default criteria still gate soundness.

    ``app.run_modes.DEFAULT_CRITERIA`` renders as "Idea correctness:
    Required" etc. (``criteria_display_strings``) before it ever reaches
    this gate; this is that exact rendering, so a future edit to either
    side that stops mapping "correct" onto scientific_soundness is
    caught here rather than only showing up as a run that stops gating on
    it.
    """
    axes = _gate_axes_for_criteria(
        [
            "Idea correctness: Required",
            "Idea novelty: Required",
            "Maximize impact: Yes",
        ]
    )
    assert axes == ("scientific_soundness", "novelty", "potential_impact")


def test_a_fatal_criterion_axis_blocks_where_the_default_gate_would_not() -> (
    None
):
    """Criteria make their axes gate decisions, not just soundness/novelty.

    Soundness and novelty are both strong here, so the historical gate
    passes the idea; the scientist's testability criterion is fatally
    weak, and with criteria supplied that must block (K4).
    """
    hypothesis = make_hypothesis(text="idea")
    review = _review_with_scores(
        {
            "scientific_soundness": 8,
            "novelty": 8,
            "testability": 1,
        }
    )

    _apply_initial_review_gate(
        [hypothesis], [review], criteria=["Discriminating experimental design"]
    )

    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_the_same_scores_stay_viable_without_criteria() -> None:
    """The criteria-driven block above is the criteria's doing.

    Identical scores with no criteria supplied keep the historical
    soundness/novelty gate, which passes this idea.
    """
    hypothesis = make_hypothesis(text="idea")
    review = _review_with_scores(
        {
            "scientific_soundness": 8,
            "novelty": 8,
            "testability": 1,
        }
    )

    _apply_initial_review_gate([hypothesis], [review], criteria=None)

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


@pytest.mark.parametrize(
    ("criteria", "expected"),
    [
        (["Translational feasibility"], "needs_revision"),
        (["Scientific soundness"], "viable"),
    ],
    ids=["rework_band_on_criterion_axis", "strong_on_selected_axis"],
)
def test_criterion_axes_use_the_same_quality_bands(
    criteria: list[str], expected: str
) -> None:
    """Criteria change which axes gate, never the bands that block.

    A 4 on a selected axis is the prompt's rework band (rankable), not
    its not-viable band; a 5 is a pass. Only the not-viable band blocks.
    """
    hypothesis = make_hypothesis(text="idea")
    review = _review_with_scores(
        {
            "scientific_soundness": 8,
            "novelty": 8,
            "testability": 4,
            "potential_impact": 4,
        }
    )

    _apply_initial_review_gate([hypothesis], [review], criteria=criteria)

    assert hypothesis.review_disposition == expected


def test_canonical_axes_keep_their_disposition_names_under_criteria() -> None:
    """Soundness/novelty failures keep their historical dispositions."""
    unsound = make_hypothesis(text="unsound")
    stale = make_hypothesis(text="stale")
    review_unsound = _review_with_scores(
        {"scientific_soundness": 2, "novelty": 8, "testability": 8}
    )
    review_stale = _review_with_scores(
        {"scientific_soundness": 8, "novelty": 1, "testability": 8}
    )

    _apply_initial_review_gate(
        [unsound, stale],
        [review_unsound, review_stale],
        criteria=["Scientific soundness", "Novelty", "Testability"],
    )

    assert unsound.review_disposition == "inaccurate"
    assert stale.review_disposition == "non_novel"


def test_a_serious_safety_score_blocks_without_criteria() -> None:
    """The reviewer's safety verdict rejects, on every run (J8).

    The rubric hands the model "10 = no concern, low = serious concern"
    on the safety axis and reserves 1-2 for "fundamentally flawed, not
    viable". A review saying both is a rejection, and it must not depend
    on the scientist having named safety among the run's criteria.
    """
    hypothesis = make_hypothesis(text="idea")
    review = _review_with_scores(
        {"scientific_soundness": 8, "novelty": 8, "safety": 1}
    )

    _apply_initial_review_gate([hypothesis], [review], criteria=None)

    assert hypothesis.review_disposition == "unsafe"
    assert not hypothesis.is_rankable()


def test_a_missing_safety_score_does_not_block() -> None:
    """An omitted safety score is a review defect, not a safety verdict.

    Production routes structured output through json_object mode, which
    does not enforce the schema, so the key can simply be absent. Reading
    that as the worst score is how the previous gate disqualified whole
    pools.
    """
    hypothesis = make_hypothesis(text="idea")
    review = _review_with_scores({"scientific_soundness": 8, "novelty": 8})

    _apply_initial_review_gate([hypothesis], [review], criteria=None)

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


def test_a_safety_score_in_the_rework_band_still_ranks() -> None:
    """Only the not-viable band blocks, exactly as for the other axes."""
    hypothesis = make_hypothesis(text="idea")
    review = _review_with_scores(
        {"scientific_soundness": 8, "novelty": 8, "safety": 4}
    )

    _apply_initial_review_gate([hypothesis], [review], criteria=None)

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


def test_a_safety_rejection_outranks_a_soundness_rejection() -> None:
    """An idea rejected on safety is reported as unsafe, not inaccurate."""
    hypothesis = make_hypothesis(text="idea")
    review = _review_with_scores(
        {"scientific_soundness": 1, "novelty": 1, "safety": 1}
    )

    _apply_initial_review_gate([hypothesis], [review], criteria=None)

    assert hypothesis.review_disposition == "unsafe"


def _gate_review(soundness: int, novelty: int) -> HypothesisReview:
    """Build a review carrying only the two axes the default gate reads."""
    return HypothesisReview(
        review_summary="summary",
        scores={"scientific_soundness": soundness, "novelty": novelty},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="feedback",
        overall_score=5,
    )


def _review_disposition_revisable_scientist_review() -> HypothesisReview:
    """A merged human review: it scores no axis this gate consults."""
    return HypothesisReview(
        review_summary="[scientist-review:7] looks promising",
        scores={"scientist_assessment": 8},
        safety_ethical_concerns="",
        detailed_feedback={"scientist_verdict": "accept"},
        constructive_feedback="promising",
        overall_score=8.0,
    )


def _blocked_hypothesis(**overrides: Any) -> Hypothesis:
    """A hypothesis the initial screen blocked as scientifically unsound."""
    hypothesis = make_hypothesis(
        reviews=[_gate_review(soundness=2, novelty=8)], **overrides
    )
    hypothesis.review_disposition = "inaccurate"
    return hypothesis


def _full_review_result(verdict: str) -> dict[str, Any]:
    """One stored mature full-review result carrying ``verdict``."""
    return {"verdict": verdict, "justification": "because"}


def test_a_deeper_review_clears_the_initial_screen_block() -> None:
    """A later full review that finds the idea sound restores ranking."""
    hypothesis = _blocked_hypothesis()
    hypothesis.enrichments[ReviewType.FULL.value] = _full_review_result("sound")

    assert not hypothesis.is_rankable()
    refresh_review_dispositions([hypothesis])

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


def test_a_deeper_review_can_still_block() -> None:
    """Revisability runs both ways: a fatal deep verdict blocks a pass."""
    hypothesis = make_hypothesis(reviews=[_gate_review(8, 8)])
    hypothesis.review_disposition = "viable"
    hypothesis.enrichments[ReviewType.FULL.value] = _full_review_result(
        "rejected"
    )

    refresh_review_dispositions([hypothesis])

    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_a_narrower_later_review_does_not_undo_a_fatal_one() -> None:
    """Simulation answers a narrower question than the full review.

    Deepest-wins is between the initial screen and the mature cascade, not
    within the cascade: a simulation whose mechanism holds says nothing
    about the correctness a full review already rejected.
    """
    hypothesis = make_hypothesis(reviews=[_gate_review(8, 8)])
    hypothesis.enrichments[ReviewType.FULL.value] = _full_review_result(
        "rejected"
    )
    hypothesis.enrichments[ReviewType.SIMULATION.value] = {"verdict": "holds"}

    refresh_review_dispositions([hypothesis])

    assert hypothesis.review_disposition == "inaccurate"


def test_a_correctness_verdict_does_not_clear_a_safety_block() -> None:
    """The cascade is never asked about safety, so it cannot answer it.

    Which quality axes matter is the scientist's call; a review reporting
    a serious safety concern is not (J8). A full review finding the idea
    scientifically sound says nothing about that concern.
    """
    hypothesis = make_hypothesis(reviews=[_gate_review(8, 8)])
    hypothesis.reviews[0].scores["safety"] = 1
    hypothesis.review_disposition = "unsafe"
    hypothesis.enrichments[ReviewType.FULL.value] = _full_review_result("sound")

    refresh_review_dispositions([hypothesis])

    assert hypothesis.review_disposition == "unsafe"
    assert not hypothesis.is_rankable()


def test_a_review_scoring_no_gated_axis_does_not_decide_the_gate() -> None:
    """A merged human review must not silently clear every block.

    It scores ``scientist_assessment`` alone, so reading it through the
    gate's neutral default would mark every blocked idea viable on any run
    a scientist reviewed.
    """
    hypothesis = _blocked_hypothesis()
    hypothesis.reviews.append(_review_disposition_revisable_scientist_review())

    refresh_review_dispositions([hypothesis])

    assert hypothesis.review_disposition == "inaccurate"


def test_the_most_recent_gated_review_wins_over_the_first() -> None:
    """Two agent reviews: the later one decides, not the one that landed."""
    hypothesis = _blocked_hypothesis()
    hypothesis.reviews.append(_gate_review(soundness=9, novelty=8))

    assert derive_review_disposition(hypothesis) == "viable"


@pytest.mark.parametrize(
    "foreign", ["evidence_blocked", "review_failed", "duplicate"]
)
def test_dispositions_owned_elsewhere_are_left_alone(foreign: str) -> None:
    """The gate re-derives only the dispositions it writes.

    ``evidence_blocked`` is the app's pre-ranking evidence gate, which
    stores the disposition it displaced and restores that itself;
    ``review_failed`` records a call that produced no review at all; and
    ``duplicate`` is proximity's archive marker.
    """
    hypothesis = make_hypothesis(reviews=[_gate_review(8, 8)])
    hypothesis.review_disposition = foreign

    refresh_review_dispositions([hypothesis])

    assert hypothesis.review_disposition == foreign


def test_an_unreviewed_hypothesis_keeps_its_absent_disposition() -> None:
    """Nothing to derive from is not the same as a clean bill of health."""
    hypothesis = make_hypothesis()

    refresh_review_dispositions([hypothesis])

    assert hypothesis.review_disposition is None


@pytest.mark.asyncio
async def test_review_node_revisits_dispositions_with_nothing_to_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pass that reviews nothing is exactly when a deeper verdict lands.

    ``review_node`` short-circuits when every hypothesis already holds a
    review. That early return is where a mature-cascade verdict recorded
    since the last pass has to be honoured, otherwise the first screen
    stays terminal for the rest of the run.
    """
    hypothesis = _blocked_hypothesis()
    hypothesis.enrichments[ReviewType.FULL.value] = _full_review_result("sound")
    state = make_state(hypotheses=[hypothesis])

    async def _fail(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("review_node must not call the LLM here")

    monkeypatch.setattr(
        "co_scientist.agents.reflection.review.call_llm_json", _fail
    )

    await review_node(state)

    assert hypothesis.is_rankable()


def test_evolution_children_re_enter_review_unreviewed() -> None:
    """An evolved idea is a fresh entrant, so review sees it again.

    Evolution never rewrites a hypothesis in place --
    ``_build_evolution_child`` constructs a new one with ``reviews=[]``
    (SSR §4, §12) -- so the rewritten idea is already selected by the same
    unreviewed filter both execution paths use, at no additional LLM cost
    beyond the review it was always going to get.
    """
    from co_scientist.agents.evolution.evolve_results import (
        _build_evolution_child,
        _RefinedFields,
    )

    parent = _blocked_hypothesis()
    child = _build_evolution_child(
        [parent],
        _RefinedFields(
            refined_text="a rewritten idea",
            explanation="why",
            experiment="how",
            refinement_summary="what changed",
            title="Rewritten",
        ),
        creation_iteration=1,
    )

    assert child.reviews == []
    assert child.review_disposition is None


# The paper's six review types (SSR §4).
_EXPECTED = {
    "initial",
    "full",
    "deep_verification",
    "observation",
    "simulation",
    "recurrent",
}


def test_all_six_review_types_are_enumerated() -> None:
    assert {rt.value for rt in ReviewType} == _EXPECTED


def test_every_review_type_resolves_to_a_prompt_and_schema() -> None:
    """Each of the six types maps to a loadable prompt and a schema."""
    for review_type in ReviewType:
        name = prompt_name_for(review_type)
        schema = schema_for(review_type)
        assert schema is not None, f"{review_type} has no schema"
        # The prompt template loads (renders) without error.
        prompt, loaded_schema = load_prompt_with_schema(
            name,
            {
                "research_goal": "A goal",
                "hypothesis_text": "A hypothesis.",
                "domain_context": "",
                "tool_instructions": "",
            },
        )
        assert prompt.strip()
        assert loaded_schema == schema


def test_full_review_schema_shape() -> None:
    """The full review scores correctness/quality and surfaces assumptions."""
    schema = schema_for(ReviewType.FULL)
    assert schema is not None
    required = set(schema["schema"]["required"])
    assert {"correctness", "assumptions", "quality_and_novelty", "verdict"} <= (
        required
    )


def test_full_review_assumption_carries_published_reasoning() -> None:
    schema = schema_for(ReviewType.FULL)
    assert schema is not None
    assumption = schema["schema"]["properties"]["assumptions"]["items"]
    assert set(assumption["required"]) == {"assumption", "reasoning", "support"}


def test_simulation_review_schema_shape() -> None:
    """The simulation review steps through the mechanism to a verdict."""
    schema = schema_for(ReviewType.SIMULATION)
    assert schema is not None
    props = schema["schema"]["properties"]
    assert props["verdict"]["enum"] == [
        "holds",
        "partially_holds",
        "breaks_down",
    ]
    assert "steps" in props and "failure_points" in props


# Both schemas below close the object (additionalProperties: False), so every
# answer the prompt asks for needs a property to land in. When one did not,
# the model invented a plausible name for it (`decisive_step`), validation
# rejected the whole response, and the node paid for a second full call --
# see the parity assertions that follow.
def test_simulation_review_answer_from_the_prompt_validates() -> None:
    """A response covering every numbered instruction fits the schema."""
    schema = schema_for(ReviewType.SIMULATION)
    assert schema is not None
    answer = {
        "model": "Two kinases coupled by a negative feedback loop.",
        "steps": [
            {"step": "The ligand binds its receptor.", "plausible": True}
        ],
        "failure_points": ["Step 3 stalls without the cofactor."],
        "robustness": "A redundant pathway blunts the effect.",
        "verdict": "partially_holds",
        "decisive_step": "Step 3.",
    }
    jsonschema.validate(instance=answer, schema=schema["schema"])


def test_full_review_answer_from_the_prompt_validates() -> None:
    """A response covering every numbered instruction fits the schema."""
    schema = schema_for(ReviewType.FULL)
    assert schema is not None
    answer = {
        "correctness": "Internally consistent.",
        "assumptions": [
            {
                "assumption": "The receptor is expressed.",
                "reasoning": "Two prior cohort studies detect it directly.",
                "support": "supported",
            }
        ],
        "quality_and_novelty": "A non-obvious combination.",
        "literature_grounding": "Two cohort studies report the association.",
        "comparison_with_knowledge_base": "Agrees with the canonical model.",
        "goal_requirements_assessment": "Meets every stated requirement.",
        "feasibility_steps": ["Run the pilot cohort.", "Read out at day 30."],
        "feasibility_reasoning": "Both steps use standard assays.",
        "impact_assessment": "Would change first-line practice.",
        "reviews_summary": {
            "executive_verdict": "The hypothesis stands, with one caveat.",
            "critical_flaws": ["The dose assumption is unsupported."],
            "addressed_objections": ["Off-target binding is ruled out."],
            "validated_risks": ["The effect may be strain-specific."],
            "supporting_arguments": ["Two cohorts show the association."],
            "alignment_and_novelty": ["Squarely on the research goal."],
            "feasibility_assessment": ["A pilot settles it in six weeks."],
            "conclusion": "Worth a pilot once the dose is pinned down.",
        },
        "verdict": "needs_revision",
        "justification": "The dose assumption is unsupported.",
    }
    jsonschema.validate(instance=answer, schema=schema["schema"])


def test_full_review_prompt_names_every_required_field() -> None:
    """A required field the prompt never mentions is never filled.

    ``reviews_summary`` was declared, optional, and unnamed by
    ``full_review.md``, so nothing ever asked a model for it. Requiring
    it fixes nothing on its own -- on a provider that enforces the
    schema, a field the prompt never asks for makes a prompt-faithful
    answer fail validation and buys the same review a second time.
    Required and named are one change, and this pins them together for
    every required field the schema declares.
    """
    schema = schema_for(ReviewType.FULL)
    assert schema is not None
    template = load_prompt_with_schema(
        "full_review",
        {
            "research_goal": "A goal",
            "hypothesis_text": "A hypothesis.",
            "domain_context": "",
            "tool_instructions": "",
        },
    )[0]
    unnamed = [
        field
        for field in schema["schema"]["required"]
        if f"`{field}`" not in template
    ]
    assert not unnamed, f"full_review.md does not name {unnamed}"


def test_full_review_prompt_names_every_reviews_summary_part() -> None:
    """The eight published parts are asked for by name, not by schema alone.

    ``reviews_summary`` is a closed object whose parts appeared nowhere
    but the schema block appended to the prompt -- the same shape that
    made the ranking judge invent a key of its own.
    """
    node = FULL_REVIEW_SCHEMA["schema"]["properties"]["reviews_summary"]
    template = (
        pathlib.Path(__file__).resolve().parents[1]
        / "src"
        / "co_scientist"
        / "prompts"
        / "templates"
        / "full_review.md"
    ).read_text()
    for part in node["properties"]:
        assert f"`{part}`" in template, part


def test_recurrent_review_adapts_full_review() -> None:
    """Recurrent review reuses the full-review schema with growing context."""
    assert prompt_name_for(ReviewType.RECURRENT) == "full_review"


def _agent_review(**scores: int) -> HypothesisReview:
    """Build an agent review carrying the given per-axis scores."""
    return HypothesisReview(
        review_summary="agent summary",
        scores={"scientific_soundness": 8, "novelty": 8, "safety": 9, **scores},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="feedback",
        overall_score=8,
    )


def _scientist_review_gate_scientist_review(score: int) -> HypothesisReview:
    """Build a merged scientist review as the app's merge shapes one."""
    return HypothesisReview(
        review_summary="[scientist-review:7] Scientist verdict",
        scores={"scientist_assessment": score},
        safety_ethical_concerns="",
        detailed_feedback={"scientist_verdict": "oppose"},
        constructive_feedback="the control cannot distinguish the mechanism",
        overall_score=float(score),
        reviewer=SCIENTIST_REVIEWER,
    )


def _hypothesis_with(*reviews: HypothesisReview) -> Hypothesis:
    """Build a hypothesis holding the given reviews, in order."""
    hypothesis = make_hypothesis("A proposed mechanism for kinase X")
    hypothesis.reviews.extend(reviews)
    return hypothesis


def test_a_scientist_review_alone_is_not_a_peer_review() -> None:
    """The run still owes an agent review to a human-reviewed idea."""
    assert not has_peer_review(
        _hypothesis_with(_scientist_review_gate_scientist_review(2))
    )
    assert has_peer_review(_hypothesis_with(_agent_review()))
    assert has_peer_review(
        _hypothesis_with(
            _scientist_review_gate_scientist_review(2), _agent_review()
        )
    )


def test_the_scheduler_still_counts_a_human_reviewed_idea_unreviewed() -> None:
    """Policy step 5 forces a review pass before ranking or evolving."""
    state = make_state()
    state["hypotheses"] = [
        _hypothesis_with(_scientist_review_gate_scientist_review(8))
    ]

    stats = _compute_stats(state, {})

    assert stats.reviewed_count == 0
    assert stats.unreviewed_count == 1


def test_an_opposing_scientist_verdict_withholds_the_idea() -> None:
    """An expert's oppose reaches the disposition the tournament reads."""
    hypothesis = _hypothesis_with(
        _agent_review(),
        _scientist_review_gate_scientist_review(NOT_VIABLE_SCORE),
    )

    assert refresh_review_dispositions([hypothesis]) == 1
    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_a_revise_verdict_demotes_without_withholding() -> None:
    """The rework band ranks and publishes, as it does for an agent review."""
    hypothesis = _hypothesis_with(
        _agent_review(),
        _scientist_review_gate_scientist_review(NEEDS_REVISION_SCORE),
    )

    assert derive_review_disposition(hypothesis) == "needs_revision"
    assert hypothesis.is_rankable()


def test_a_supporting_verdict_clears_a_quality_block() -> None:
    """The scientist outranks the model on the axes the model judged."""
    hypothesis = _hypothesis_with(
        _agent_review(scientific_soundness=1),
        _scientist_review_gate_scientist_review(8),
    )

    assert derive_review_disposition(hypothesis) == "viable"


def test_a_supporting_verdict_cannot_clear_a_safety_block() -> None:
    """No human endorsement releases an idea the reviewer flagged unsafe."""
    hypothesis = _hypothesis_with(
        _agent_review(safety=1), _scientist_review_gate_scientist_review(8)
    )

    assert refresh_review_dispositions([hypothesis]) == 1
    assert hypothesis.review_disposition == "unsafe"
    assert not hypothesis.is_rankable()


def test_the_latest_scientist_verdict_wins() -> None:
    """A second review supersedes the first, as it does for agent reviews."""
    hypothesis = _hypothesis_with(
        _agent_review(),
        _scientist_review_gate_scientist_review(NOT_VIABLE_SCORE),
        _scientist_review_gate_scientist_review(8),
    )

    assert derive_review_disposition(hypothesis) == "viable"


def test_a_scientist_verdict_cannot_reopen_a_foreign_disposition() -> None:
    """Evidence and proximity own their own exclusions (see the gate)."""
    hypothesis = _hypothesis_with(
        _agent_review(), _scientist_review_gate_scientist_review(8)
    )
    hypothesis.review_disposition = "evidence_blocked"

    assert refresh_review_dispositions([hypothesis]) == 0
    assert hypothesis.review_disposition == "evidence_blocked"


def test_the_reviewer_attribution_survives_serialization() -> None:
    """Authorship rides the checkpoint, not just the live object."""
    hypothesis = _hypothesis_with(
        _agent_review(), _scientist_review_gate_scientist_review(2)
    )

    restored = Hypothesis.from_dict(hypothesis.to_dict())

    assert [review.reviewer for review in restored.reviews] == [
        "agent",
        SCIENTIST_REVIEWER,
    ]
    assert not has_peer_review(_hypothesis_with(restored.reviews[1]))


def _scheduler_pool() -> WorkflowState:
    """A settled pool plus one just-admitted, unreviewed contribution."""
    settled = _hypothesis_with(_agent_review())
    settled.win_count, settled.loss_count = 1, 1
    admitted = _hypothesis_with(_scientist_review_gate_scientist_review(8))
    return make_state(
        hypotheses=[settled, admitted],
        current_iteration=1,
        max_iterations=5,
    )


def test_an_admitted_idea_does_not_pull_the_run_into_ranking() -> None:
    """Coverage is owed to reviewed ideas, so review still comes first.

    The tournament's coverage floor is checked (step 3) above the
    unreviewed backlog (step 6), so an idea that is rankable with no
    matches is itself a reason to rank -- which would put a contributed
    hypothesis into the tournament ungated, through the front door,
    whether or not its steering message survived to this decision.
    """
    state = _scheduler_pool()

    decision = required_transition(
        _compute_stats(state, {}), _default_budget(state)
    )

    assert decision is not None
    assert decision.next_task is TaskType.REFLECT


def test_steering_still_schedules_generation_when_it_arrives() -> None:
    """A steer that reaches this decision outranks the review backlog."""
    state = _scheduler_pool()
    state["pending_steering"] = True

    decision = required_transition(
        _compute_stats(state, {}), _default_budget(state)
    )

    assert decision is not None
    assert decision.next_task is TaskType.GENERATE


def _modes(hypothesis: object, iteration: int) -> list[str]:
    """The review modes due, as the strings the schedulers key on."""
    return [review.value for review in reviews_needed(hypothesis, iteration)]  # type: ignore[arg-type]


class TestFirstMaturity:
    def test_a_fresh_hypothesis_is_owed_both(self) -> None:
        assert _modes(make_hypothesis(text="a"), 0) == ["full", "simulation"]

    def test_a_succeeded_simulation_is_not_re_issued(self) -> None:
        """The defect: a review that passed, re-run because another failed.

        Harmless while both were one LLM call. Not harmless once the
        simulation review runs a tool loop it pays for per firing -- and
        the cost recurred every iteration, because nothing about a
        failing full review stops the next iteration asking again.
        """
        hypothesis = make_hypothesis(text="a")
        hypothesis.enrichments["simulation"] = {"verdict": "breaks_down"}

        for iteration in (0, 1, 2):
            assert _modes(hypothesis, iteration) == ["full"]

    def test_a_succeeded_full_moves_the_hypothesis_on(self) -> None:
        # Maturity still turns on the full review; only the redundant
        # re-issue is gone.
        hypothesis = make_hypothesis(text="a")
        hypothesis.enrichments["full"] = {"verdict": "sound"}

        assert _modes(hypothesis, 1) == ["recurrent"]


class TestOnceMature:
    def test_a_recurrent_review_is_owed_once_per_iteration(self) -> None:
        hypothesis = make_hypothesis(text="a")
        hypothesis.enrichments["full"] = {"verdict": "sound"}
        hypothesis.enrichments["recurrent_review_iteration"] = 2

        assert _modes(hypothesis, 2) == []
        assert _modes(hypothesis, 3) == ["recurrent"]


class TestWhatIsDeliberatelyNotRetried:
    """A failed simulation review is not re-issued once the run matures."""

    def test_a_failed_simulation_is_not_retried_after_full_succeeds(
        self,
    ) -> None:
        """Recorded as a decision, because it is one and it is arguable.

        Maturity turns on the full review, so a hypothesis whose full
        review succeeded moves to recurrent reviews carrying whatever
        simulation result it got -- including none. Retrying the
        simulation later would mean a fresh tool loop, on the tiers where
        that is the expensive part, to fill in a review the hypothesis
        has already been assessed without. The complete review set is
        worth less than the cost of completing it, so the gap stands.

        If that trade is ever revisited, this test is the thing to
        change; today it stops the behaviour being re-derived by
        accident in either direction.
        """
        hypothesis = make_hypothesis(text="a")
        hypothesis.enrichments["full"] = {"verdict": "sound"}

        for iteration in (0, 1, 2):
            assert "simulation" not in _modes(hypothesis, iteration)
            hypothesis.enrichments["recurrent_review_iteration"] = iteration
