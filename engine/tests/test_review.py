from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from typing import Any

import pytest

import co_scientist.agents.reflection.review_gate as review_recheck
from co_scientist.agents.reflection import comprehensive_reflection, review
from co_scientist.agents.reflection.comprehensive_reflection import (
    comprehensive_reflection_node,
)
from co_scientist.agents.reflection.review import (
    _match_batch_entries_to_hypotheses,
    _review_from_response,
    _sanitize_review_scores,
    review_node,
)
from co_scientist.agents.reflection.review_gate import (
    RECHECK_REVIEW_TYPE,
    ReviewType,
    mature_review_summary,
    recheck_targets,
    store_mature_review_result,
)
from co_scientist.constants import COMPARATIVE_BATCH_THRESHOLD
from co_scientist.models import Hypothesis, HypothesisReview
from co_scientist.schemas.review import (
    REVIEW_BATCH_SCHEMA,
    REVIEW_SCHEMA,
    REVIEW_SCORE_MAXIMUM,
    REVIEW_SCORE_MINIMUM,
)
from tests._llm_fake import stub_call_llm_json
from tests._state import make_hypothesis, make_review, make_state


def test_initial_review_gate_classifies_accuracy_and_novelty_failures() -> None:
    hypotheses = [make_hypothesis(text=f"idea {index}") for index in range(4)]
    scores = [(2, 8), (8, 2), (2, 2), (8, 8)]
    reviews = [_review(soundness, novelty) for soundness, novelty in scores]

    review._apply_initial_review_gate(hypotheses, reviews)

    assert [hypothesis.review_disposition for hypothesis in hypotheses] == [
        "inaccurate",
        "non_novel",
        "inaccurate_and_non_novel",
        "viable",
    ]


def _review(soundness: int | None, novelty: int | None) -> HypothesisReview:
    scores: dict[str, int] = {}
    if soundness is not None:
        scores["scientific_soundness"] = soundness
    if novelty is not None:
        scores["novelty"] = novelty
    return make_review(
        review_summary="summary",
        scores=scores,
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="feedback",
        overall_score=5,
    )


@pytest.mark.parametrize(
    ("soundness", "novelty", "expected"),
    [
        (2, 8, "inaccurate"),
        (8, 2, "non_novel"),
        (3, 8, "needs_revision"),
        (8, 4, "needs_revision"),
        (5, 5, "viable"),
    ],
    ids=[
        "not_viable_soundness_blocks",
        "not_viable_novelty_blocks",
        "rework_soundness_still_ranks",
        "rework_novelty_still_ranks",
        "moderate_is_viable",
    ],
)
def test_only_the_non_viable_band_blocks_the_tournament(
    soundness: int, novelty: int, expected: str
) -> None:
    """Comparative reviews must spread scores; that does not imply fatal
    defects."""
    hypothesis = make_hypothesis(text="idea")

    review._apply_initial_review_gate(
        [hypothesis], [_review(soundness, novelty)]
    )

    assert hypothesis.review_disposition == expected


def test_needs_revision_still_enters_the_tournament() -> None:
    """Overblocking irreversibly collapses the survivor pool."""
    weak = make_hypothesis(text="weak")
    unsound = make_hypothesis(text="unsound")

    review._apply_initial_review_gate(
        [weak, unsound], [_review(3, 3), _review(1, 1)]
    )

    assert weak.is_rankable()
    assert not unsound.is_rankable()


def test_a_missing_score_does_not_disqualify_the_idea() -> None:
    """Missing JSON fields are parsing defects, not worst-case review scores."""
    hypothesis = make_hypothesis(text="idea")

    review._apply_initial_review_gate([hypothesis], [_review(None, 8)])

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


def _batch_entry(scores: dict[str, int]) -> dict[str, Any]:
    return {
        "review_summary": "batch summary",
        "scores": scores,
        "safety_ethical_concerns": "none noted",
        "detailed_feedback": {"novelty": "ok"},
        "constructive_feedback": "tighten the experiment",
    }


def _stub_batch(
    monkeypatch: pytest.MonkeyPatch, score_dicts: list[dict[str, int]]
) -> None:
    stub_call_llm_json(
        monkeypatch,
        review,
        {"reviews": [_batch_entry(scores) for scores in score_dicts]},
    )


def _assert_batch_review(
    hyp: Any, overall: float, scores: dict[str, int]
) -> None:
    assert len(hyp.reviews) == 1
    rev = hyp.reviews[0]
    assert rev.overall_score == pytest.approx(overall)
    assert rev.review_summary == "batch summary"
    assert rev.scores == scores
    assert rev.safety_ethical_concerns == "none noted"
    assert rev.constructive_feedback == "tighten the experiment"
    assert hyp.score == pytest.approx(overall)


async def test_review_node_gates_on_the_run_criteria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scores = {
        "scientific_soundness": 9,
        "novelty": 9,
        "testability": 1,
    }
    stub_call_llm_json(monkeypatch, review, {"reviews": [_batch_entry(scores)]})
    with_criteria = make_hypothesis(text="idea")
    without_criteria = make_hypothesis(text="idea")

    await review_node(
        state=make_state(
            hypotheses=[with_criteria],
            criteria=["Discriminating experimental design"],
        )
    )
    await review_node(state=make_state(hypotheses=[without_criteria]))

    assert with_criteria.review_disposition == "inaccurate"
    assert not with_criteria.is_rankable()
    assert without_criteria.review_disposition == "viable"
    assert without_criteria.is_rankable()


async def test_comparative_batch_attaches_reviews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hyps = [make_hypothesis(text=f"h{i}") for i in range(3)]
    assert len(hyps) <= COMPARATIVE_BATCH_THRESHOLD
    expected_scores = [
        {"soundness": 8, "novelty": 6},
        {"soundness": 4, "novelty": 6},
        {"soundness": 9, "novelty": 9},
    ]
    _stub_batch(monkeypatch, expected_scores)

    result = await review_node(state=make_state(hypotheses=hyps))

    returned = result["hypotheses"]
    assert len(returned) == 3
    assert result["messages"][0]["metadata"]["strategy"] == "comparative batch"
    assert result["metrics"].llm_calls == 1
    assert result["metrics"].reviews_count == 3
    for hyp, overall, scores in zip(
        returned, [7.0, 5.0, 9.0], expected_scores, strict=True
    ):
        _assert_batch_review(hyp, overall, scores)


async def test_parallel_individual_attaches_reviews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    count = COMPARATIVE_BATCH_THRESHOLD + 1
    hyps = [make_hypothesis(text=f"h{i}") for i in range(count)]
    stub_call_llm_json(
        monkeypatch,
        review,
        {
            "review_summary": "individual summary",
            "scores": {"soundness": 7, "novelty": 5},
            "safety_ethical_concerns": "no concerns",
            "detailed_feedback": {"relevance": "strong"},
            "constructive_feedback": "add controls",
        },
    )

    result = await review_node(state=make_state(hypotheses=hyps))

    returned = result["hypotheses"]
    assert len(returned) == count
    assert result["messages"][0]["metadata"]["strategy"] == "parallel"
    assert result["metrics"].llm_calls == count
    assert result["metrics"].reviews_count == count
    for hyp in returned:
        assert len(hyp.reviews) == 1
        rev = hyp.reviews[0]
        assert rev.overall_score == pytest.approx(6.0)
        assert rev.review_summary == "individual summary"
        assert rev.scores == {"soundness": 7, "novelty": 5}
        assert rev.safety_ethical_concerns == "no concerns"
        assert rev.constructive_feedback == "add controls"
        assert hyp.score == pytest.approx(6.0)


async def test_individual_missing_scores_defaults_to_overall_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    count = COMPARATIVE_BATCH_THRESHOLD + 1
    hyps = [make_hypothesis(text=f"h{i}") for i in range(count)]
    stub_call_llm_json(
        monkeypatch,
        review,
        {
            "review_summary": "no criteria scores",
            "scores": {},
            "overall_score": 42.0,
            "safety_ethical_concerns": "",
            "detailed_feedback": {},
            "constructive_feedback": "",
        },
    )

    result = await review_node(state=make_state(hypotheses=hyps))

    returned = result["hypotheses"]
    assert len(returned) == count
    assert result["messages"][0]["metadata"]["strategy"] == "parallel"
    for hyp in returned:
        assert len(hyp.reviews) == 1
        assert hyp.reviews[0].overall_score == pytest.approx(42.0)
        assert hyp.score == pytest.approx(42.0)


async def test_empty_hypotheses_returns_empty_without_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def fail(**_: Any) -> dict[str, Any]:
        raise AssertionError("no LLM call expected for an empty pool")

    monkeypatch.setattr(review, "call_llm_json", fail)

    result = await review_node(state=make_state(hypotheses=[]))

    assert result["hypotheses"] == []
    assert result["messages"][0]["metadata"]["strategy"] == "skipped"


async def test_second_invocation_reviews_only_new_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def counting_stub(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        count = len(
            re.findall(
                r"^\*\*Hypothesis \d+:\*\*$", kwargs["prompt"], re.MULTILINE
            )
        )
        return {
            "reviews": [_batch_entry({"soundness": 6}) for _ in range(count)]
        }

    monkeypatch.setattr(review, "call_llm_json", counting_stub)

    hyps = [make_hypothesis(text=f"h{i}") for i in range(3)]
    first = await review_node(state=make_state(hypotheses=hyps))
    assert len(calls) == 1
    assert first["metrics"].reviews_count == 3

    hyps.append(make_hypothesis(text="child"))
    second = await review_node(state=make_state(hypotheses=hyps))

    assert len(calls) == 2
    assert "**Hypothesis 1:**\nchild" in calls[1]["prompt"]
    assert not re.search(r"^h[0-2]$", calls[1]["prompt"], re.MULTILINE)
    assert second["metrics"].reviews_count == 1
    assert [len(h.reviews) for h in second["hypotheses"]] == [1, 1, 1, 1]


def _entry(index: int | None, summary: str) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "review_summary": summary,
        "scores": {"scientific_soundness": 7, "novelty": 7},
        "safety_ethical_concerns": "",
        "detailed_feedback": {},
        "constructive_feedback": "",
    }
    if index is not None:
        entry["hypothesis_index"] = index
    return entry


def test_score_fields_are_bounded_to_the_rubric_range() -> None:
    batch_items = REVIEW_BATCH_SCHEMA["schema"]["properties"]["reviews"][
        "items"
    ]
    for schema in (REVIEW_SCHEMA["schema"], batch_items):
        scores = schema["properties"]["scores"]["properties"]
        for criterion, field in scores.items():
            assert field["minimum"] == REVIEW_SCORE_MINIMUM, criterion
            assert field["maximum"] == REVIEW_SCORE_MAXIMUM, criterion


def test_novelty_review_schema_carries_the_published_two_lists() -> None:
    batch_items = REVIEW_BATCH_SCHEMA["schema"]["properties"]["reviews"][
        "items"
    ]
    for schema in (REVIEW_SCHEMA["schema"], batch_items):
        novelty_review = schema["properties"]["novelty_review"]
        assert set(novelty_review["required"]) == {
            "already_explored",
            "novel_aspects",
        }
        for name in ("already_explored", "novel_aspects"):
            assert novelty_review["properties"][name]["type"] == "array"


def test_novelty_review_lists_parse_onto_the_review() -> None:
    review = _review_from_response(
        {
            "review_summary": "Sound and moderately novel.",
            "scores": {},
            "novelty_review": {
                "already_explored": [
                    "TDP-43 mislocalization is well documented.",
                    "  ",
                ],
                "novel_aspects": ["Stress-induced Nup PTMs are new."],
            },
        }
    )
    assert review.already_explored == [
        "TDP-43 mislocalization is well documented."
    ]
    assert review.novel_aspects == ["Stress-induced Nup PTMs are new."]


def test_novelty_review_missing_or_malformed_degrades_to_empty() -> None:
    review = _review_from_response({"review_summary": "s", "scores": {}})
    assert review.already_explored == []
    assert review.novel_aspects == []

    review = _review_from_response(
        {"review_summary": "s", "scores": {}, "novelty_review": "oops"}
    )
    assert review.already_explored == []
    assert review.novel_aspects == []


def test_batch_schema_identifies_by_index_and_never_echoes_text() -> None:
    """Echoed hypotheses scale output with input and truncate identical
    retries."""
    items = REVIEW_BATCH_SCHEMA["schema"]["properties"]["reviews"]["items"]
    assert "hypothesis_index" in items["properties"]
    assert "hypothesis_text" not in items["properties"]


def test_out_of_range_scores_are_dropped_not_clamped() -> None:
    """Clamping a malformed score to the floor would create a fatal verdict."""
    sanitized = _sanitize_review_scores(
        {
            "scientific_soundness": 0,
            "novelty": 12,
            "relevance": "high",
            "testability": True,
            "safety": 8,
        }
    )
    assert sanitized == {"safety": 8}


def test_valid_scores_pass_through_as_integers() -> None:
    assert _sanitize_review_scores({"novelty": 7, "clarity": 8.0}) == {
        "novelty": 7,
        "clarity": 8,
    }


def test_entries_match_by_hypothesis_index_not_list_order() -> None:
    entries = [_entry(3, "third"), _entry(1, "first"), _entry(2, "second")]
    matched = _match_batch_entries_to_hypotheses(entries, 3)
    assert [entry["review_summary"] for entry in matched] == [
        "first",
        "second",
        "third",
    ]


def test_entries_without_indices_fall_back_to_list_order() -> None:
    entries = [_entry(None, "a"), _entry(None, "b")]
    matched = _match_batch_entries_to_hypotheses(entries, 2)
    assert [entry["review_summary"] for entry in matched] == ["a", "b"]


def test_invalid_and_duplicate_indices_fall_back_positionally() -> None:
    entries = [
        _entry(99, "out-of-range"),
        _entry(1, "real first"),
        _entry(1, "duplicate"),
        _entry(None, "unnumbered"),
    ]
    matched = _match_batch_entries_to_hypotheses(entries, 3)
    assert [entry["review_summary"] for entry in matched] == [
        "real first",
        "out-of-range",
        "duplicate",
    ]


async def test_one_malformed_entry_does_not_abort_the_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed entries must not discard healthy sibling reviews."""
    stub_call_llm_json(
        monkeypatch,
        review,
        {"reviews": [_entry(3, "third"), "garbage", _entry(1, "first")]},
    )
    hyps = [make_hypothesis(text=f"h{i}") for i in range(3)]

    result = await review_node(state=make_state(hypotheses=hyps))

    returned = result["hypotheses"]
    assert [
        h.reviews[0].review_summary for h in (returned[0], returned[2])
    ] == [
        "first",
        "third",
    ]
    assert returned[1].reviews == []
    assert result["metrics"].reviews_count == 2
    assert result["messages"][0]["metadata"]["review_failures"] == 1


async def test_failed_review_is_retried_on_the_next_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stamping a placeholder review prevents every later retry."""
    responses: Iterator[dict[str, Any]] = iter(
        [
            {"reviews": [_entry(1, "first"), "garbage"]},
            {"reviews": [_entry(1, "second chance")]},
        ]
    )

    async def scripted(**_: Any) -> dict[str, Any]:
        return next(responses)

    monkeypatch.setattr(review, "call_llm_json", scripted)
    hyps = [make_hypothesis(text="h1"), make_hypothesis(text="h2")]

    first = await review_node(state=make_state(hypotheses=hyps))
    assert first["metrics"].reviews_count == 1

    second = await review_node(state=make_state(hypotheses=hyps))

    assert second["metrics"].reviews_count == 1
    assert [h.reviews[-1].review_summary for h in second["hypotheses"]] == [
        "first",
        "second chance",
    ]


async def test_parallel_individual_isolates_a_failed_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def flaky(**kwargs: Any) -> dict[str, Any]:
        if "poisoned" in str(kwargs["prompt"]):
            raise RuntimeError("provider error")
        return {
            "review_summary": "individual summary",
            "scores": {"novelty": 6},
            "safety_ethical_concerns": "",
            "detailed_feedback": {},
            "constructive_feedback": "",
        }

    monkeypatch.setattr(review, "call_llm_json", flaky)
    count = COMPARATIVE_BATCH_THRESHOLD + 1
    hyps = [
        make_hypothesis(text="poisoned idea" if i == 2 else f"idea {i}")
        for i in range(count)
    ]

    result = await review_node(state=make_state(hypotheses=hyps))

    reviewed = [h for h in result["hypotheses"] if h.reviews]
    assert len(reviewed) == count - 1
    assert result["hypotheses"][2].reviews == []
    assert result["metrics"].reviews_count == count - 1
    assert result["messages"][0]["metadata"]["review_failures"] == 1


async def test_batch_review_degrades_to_zero_reviews_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_call_llm_json(monkeypatch, review, {"reviews": []})
    hyps = [make_hypothesis(text=f"h{i}") for i in range(3)]

    result = await review_node(state=make_state(hypotheses=hyps))

    assert result["metrics"].reviews_count == 0
    assert result["messages"][0]["metadata"]["review_failures"] == 3
    assert all(not h.reviews for h in result["hypotheses"])


def _blocked(index: int) -> Hypothesis:
    return make_hypothesis(
        text=f"blocked idea {index}",
        reviews=[make_review(scores={"scientific_soundness": 2, "novelty": 8})],
        review_disposition="inaccurate",
    )


def _viable(index: int) -> Hypothesis:
    return make_hypothesis(
        text=f"viable idea {index}", review_disposition="viable"
    )


def _incident_pool() -> list[Hypothesis]:
    return [_blocked(i) for i in range(20)] + [_viable(i) for i in range(2)]


class _ReviewStub:
    def __init__(self, verdict: str | None) -> None:
        self.verdict = verdict
        self.calls: Counter[tuple[str, str]] = Counter()

    async def __call__(
        self, state: Any, hypothesis: Hypothesis, review_type: ReviewType
    ) -> Any:
        self.calls[(review_type.value, hypothesis.id)] += 1
        result = None if self.verdict is None else {"verdict": self.verdict}
        return comprehensive_reflection._ReviewRun(review_type, result, None)

    def rechecks(self, hypotheses: list[Hypothesis]) -> int:
        return sum(
            self.calls[(RECHECK_REVIEW_TYPE.value, hypothesis.id)]
            for hypothesis in hypotheses
        )


def _stub_reviews(
    monkeypatch: pytest.MonkeyPatch, verdict: str | None
) -> _ReviewStub:
    stub = _ReviewStub(verdict)
    monkeypatch.setattr(comprehensive_reflection, "review_hypothesis", stub)
    return stub


def _state(hypotheses: list[Hypothesis]) -> Any:
    return make_state(hypotheses=hypotheses, articles_with_reasoning=None)


@pytest.mark.asyncio
async def test_a_recheck_clears_the_ideas_a_deeper_review_finds_sound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deep correctness checks supersede the shallow admission screen."""
    pool = _incident_pool()
    blocked = pool[:20]
    stub = _stub_reviews(monkeypatch, "sound")

    await comprehensive_reflection_node(_state(pool))

    assert stub.rechecks(blocked) == 20
    assert all(hypothesis.is_rankable() for hypothesis in pool)


@pytest.mark.asyncio
async def test_a_second_cycle_issues_no_further_recheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _incident_pool()
    blocked = pool[:20]
    stub = _stub_reviews(monkeypatch, "sound")
    state = _state(pool)

    await comprehensive_reflection_node(state)
    first_cycle = stub.rechecks(blocked)
    stub.calls.clear()
    await comprehensive_reflection_node(state)

    assert first_cycle == 20
    assert stub.rechecks(blocked) == 0


@pytest.mark.asyncio
async def test_a_confirmed_block_is_not_rechecked_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unchanged fatal findings do not justify repeated per-cycle calls."""
    pool = _incident_pool()
    blocked = pool[:20]
    stub = _stub_reviews(monkeypatch, "rejected")
    state = _state(pool)

    await comprehensive_reflection_node(state)
    stub.calls.clear()
    await comprehensive_reflection_node(state)

    assert not any(hypothesis.is_rankable() for hypothesis in blocked)
    assert stub.rechecks(blocked) == 0


@pytest.mark.asyncio
async def test_a_failed_recheck_call_still_spends_its_one_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = [_blocked(0)]
    stub = _stub_reviews(monkeypatch, None)
    state = _state(pool)

    await comprehensive_reflection_node(state)
    await comprehensive_reflection_node(state)

    assert stub.rechecks(pool) == 1


def test_the_recheck_marker_survives_a_checkpoint_round_trip() -> None:
    hypothesis = _blocked(0)
    review_recheck.mark_recheck_issued(hypothesis)

    restored = Hypothesis.from_dict(hypothesis.to_dict())

    assert recheck_targets([restored]) == []


def test_the_run_wide_ceiling_bounds_a_pathological_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(review_recheck, "MAX_RECHECKS_PER_RUN", 3)
    pool = _incident_pool()

    first = recheck_targets(pool)
    for hypothesis in first:
        review_recheck.mark_recheck_issued(hypothesis)
    second = recheck_targets(pool)

    assert len(first) == 3
    assert second == []


def test_the_gates_this_one_does_not_own_are_left_alone() -> None:
    foreign = ["unsafe", "evidence_blocked", "review_failed", "duplicate"]
    pool = []
    for disposition in foreign:
        hypothesis = _blocked(0)
        hypothesis.review_disposition = disposition
        pool.append(hypothesis)

    assert recheck_targets(pool) == []


def test_an_idea_the_cascade_already_rejected_is_not_rechecked() -> None:
    hypothesis = _blocked(0)
    hypothesis.enrichments["full"] = {"verdict": "rejected"}

    assert recheck_targets([hypothesis]) == []


def _full_review(verdict: str, **overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "correctness": "checked",
        "assumptions": [],
        "quality_and_novelty": "fine",
        "literature_grounding": "grounded",
        "verdict": verdict,
        "justification": "because",
    }
    result.update(overrides)
    return result


def _simulation_review(verdict: str, **overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "model": "the model",
        "steps": [],
        "failure_points": [],
        "robustness": "robust",
        "verdict": verdict,
        "decisive_step": "step three",
    }
    result.update(overrides)
    return result


def _store(
    hypothesis: Hypothesis,
    review_type: ReviewType,
    result: dict[str, object],
    iteration: int = 1,
) -> None:
    store_mature_review_result(hypothesis, review_type, result, iteration)


def test_a_fatal_full_review_blocks_the_tournament() -> None:
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(hypothesis, ReviewType.FULL, _full_review("rejected"))

    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_a_breaking_simulation_blocks_the_tournament() -> None:
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(
        hypothesis,
        ReviewType.SIMULATION,
        _simulation_review("breaks_down"),
    )

    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_a_recurrent_rejection_blocks_like_a_full_review() -> None:
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(hypothesis, ReviewType.RECURRENT, _full_review("rejected"))

    assert hypothesis.review_disposition == "inaccurate"
    assert hypothesis.enrichments["recurrent_review_iteration"] == 1


@pytest.mark.parametrize(
    ("review_type", "result", "expected"),
    [
        (ReviewType.FULL, _full_review("sound"), "viable"),
        (ReviewType.SIMULATION, _simulation_review("holds"), "viable"),
        (
            ReviewType.SIMULATION,
            _simulation_review("partially_holds"),
            "viable",
        ),
        (
            ReviewType.FULL,
            _full_review("needs_revision"),
            "needs_revision",
        ),
    ],
    ids=[
        "sound_full_review_keeps_viable",
        "holding_simulation_keeps_viable",
        "partial_simulation_still_ranks",
        "needs_revision_publishes_but_leaves_cascade",
    ],
)
def test_only_the_not_viable_band_blocks(
    review_type: ReviewType, result: dict[str, object], expected: str
) -> None:
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(hypothesis, review_type, result)

    assert hypothesis.review_disposition == expected
    assert hypothesis.is_rankable()


def test_a_deeper_review_reverses_the_initial_screen() -> None:
    hypothesis = make_hypothesis(text="idea", review_disposition="inaccurate")

    _store(hypothesis, ReviewType.FULL, _full_review("sound"))

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


def test_a_narrower_review_does_not_reverse_a_fatal_one() -> None:
    """A narrower mechanism simulation cannot overrule a correctness failure."""
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(hypothesis, ReviewType.FULL, _full_review("rejected"))
    _store(hypothesis, ReviewType.SIMULATION, _simulation_review("holds"))

    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_a_fatal_simulation_wins_over_a_revising_full_review() -> None:
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(hypothesis, ReviewType.FULL, _full_review("needs_revision"))
    _store(
        hypothesis,
        ReviewType.SIMULATION,
        _simulation_review("breaks_down"),
    )

    assert hypothesis.review_disposition == "inaccurate"


def test_store_keeps_the_result_on_the_enrichments() -> None:
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")
    result = _full_review("sound")

    _store(hypothesis, ReviewType.FULL, result)

    assert hypothesis.enrichments["full"] == result


def test_summary_projects_verdicts_and_strips_retrieval_bookkeeping() -> None:
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")
    _store(
        hypothesis,
        ReviewType.FULL,
        _full_review(
            "rejected",
            justification="the mechanism is circular",
            assumptions=[
                {"assumption": "protein X binds Y", "support": "likely_false"},
                {"assumption": "dose is safe", "support": "supported"},
            ],
            retrieval_queries=["query"],
            retrieved_articles=[{"title": "a paper"}],
        ),
    )
    _store(
        hypothesis,
        ReviewType.SIMULATION,
        _simulation_review(
            "breaks_down",
            failure_points=["step two fails", "step four diverges"],
        ),
    )

    summary = mature_review_summary(hypothesis.enrichments)

    assert summary is not None
    assert summary["full"] == {
        "verdict": "rejected",
        "justification": "the mechanism is circular",
        "assumptions_likely_false": ["protein X binds Y"],
    }
    assert summary["simulation"] == {
        "verdict": "breaks_down",
        "decisive_step": "step three",
        "failure_points": ["step two fails", "step four diverges"],
    }
    serialized = repr(summary)
    assert "retrieved_articles" not in serialized
    assert "retrieval_queries" not in serialized


def test_summary_is_none_before_any_mature_review_has_run() -> None:
    assert mature_review_summary(None) is None
    assert mature_review_summary({}) is None
    assert mature_review_summary({"claim_gate": {"decision": "pass"}}) is None


def test_summary_clips_long_prose_fields() -> None:
    long_text = "x" * 5000
    summary = mature_review_summary(
        {
            "full": _full_review("needs_revision", justification=long_text),
        }
    )

    assert summary is not None
    assert len(summary["full"]["justification"]) <= 400
    assert summary["full"]["justification"].endswith("...")


def test_offline_canned_outputs_leave_dispositions_alone() -> None:
    """Schema enum order otherwise makes canned output accidentally change
    admission."""
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(hypothesis, ReviewType.FULL, _full_review("sound"))
    _store(hypothesis, ReviewType.SIMULATION, _simulation_review("holds"))

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


@pytest.mark.parametrize(
    ("review_type", "verdict"),
    [
        (ReviewType.FULL, "rejected"),
        (ReviewType.SIMULATION, "breaks_down"),
        (ReviewType.RECURRENT, "rejected"),
    ],
)
def test_fatal_verdicts_are_recognized_per_review_type(
    review_type: ReviewType, verdict: str
) -> None:
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    result = (
        _simulation_review(verdict)
        if review_type is ReviewType.SIMULATION
        else _full_review(verdict)
    )
    _store(hypothesis, review_type, result)

    assert not hypothesis.is_rankable()


def test_go_no_go_recommendation_cannot_gate_the_disposition() -> None:
    """Report recommendations are display content, not admission decisions."""
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(
        hypothesis,
        ReviewType.FULL,
        _full_review(
            "sound",
            go_no_go_recommendation="No-Go — do not pursue.",
            time_to_verdict="Short",
        ),
    )

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


def test_summary_excludes_go_no_go_fields() -> None:
    summary = mature_review_summary(
        {
            "full": _full_review(
                "needs_revision",
                go_no_go_recommendation="Go — pursue wet-lab validation.",
                time_to_verdict="2-4 weeks",
            )
        }
    )

    assert summary is not None
    assert "go_no_go_recommendation" not in summary["full"]
    assert "time_to_verdict" not in summary["full"]
