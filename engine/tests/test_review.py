"""Offline contracts for review."""

from __future__ import annotations

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
    """Low soundness/novelty scores become explicit tournament exclusions."""
    hypotheses = [make_hypothesis(text=f"idea {index}") for index in range(4)]
    scores = [(2, 8), (8, 2), (2, 2), (8, 8)]
    reviews = [
        HypothesisReview(
            review_summary="summary",
            scores={"scientific_soundness": soundness, "novelty": novelty},
            safety_ethical_concerns="none",
            detailed_feedback={},
            constructive_feedback="feedback",
            overall_score=5,
        )
        for soundness, novelty in scores
    ]

    review._apply_initial_review_gate(hypotheses, reviews)

    assert [hypothesis.review_disposition for hypothesis in hypotheses] == [
        "inaccurate",
        "non_novel",
        "inaccurate_and_non_novel",
        "viable",
    ]


def _review(soundness: int | None, novelty: int | None) -> HypothesisReview:
    """Build a review carrying only the two scores the gate reads."""
    scores: dict[str, int] = {}
    if soundness is not None:
        scores["scientific_soundness"] = soundness
    if novelty is not None:
        scores["novelty"] = novelty
    return HypothesisReview(
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
    """The gate follows the review prompt's own 1-10 rubric.

    The prompt calls 1-2 "fundamentally flawed, not viable" and 3-4 "major
    deficiencies, needs substantial rework" -- a revise signal, not a
    discard signal. Blocking at <= 3 swept the rework band into permanent
    disqualification, and since the batch prompt *requires* the model to
    spread scores across the pool, a low scorer is manufactured on every
    run whatever the absolute quality.
    """
    hypothesis = make_hypothesis(text="idea")

    review._apply_initial_review_gate(
        [hypothesis], [_review(soundness, novelty)]
    )

    assert hypothesis.review_disposition == expected


def test_needs_revision_still_enters_the_tournament() -> None:
    """The rework band ranks and publishes; only the non-viable band does not.

    The disposition is never revisited, so a blocked idea is excluded from
    ranking for the rest of the run -- and the surviving pool is what
    evolution breeds from, so an over-eager gate collapses the run's
    diversity as well as its leaderboard.
    """
    weak = make_hypothesis(text="weak")
    unsound = make_hypothesis(text="unsound")

    review._apply_initial_review_gate(
        [weak, unsound], [_review(3, 3), _review(1, 1)]
    )

    assert weak.is_rankable()
    assert not unsound.is_rankable()


def test_a_missing_score_does_not_disqualify_the_idea() -> None:
    """An absent score is a review defect; the idea should not pay for it.

    Production routes structured output through a provider in json_object
    mode, which does not enforce the schema, so a criterion can simply be
    missing. Defaulting to 0 read that as the worst possible score.
    """
    hypothesis = make_hypothesis(text="idea")

    review._apply_initial_review_gate([hypothesis], [_review(None, 8)])

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


def _batch_entry(scores: dict[str, int]) -> dict[str, Any]:
    """Build one comparative-batch review entry with the given scores.

    Args:
        scores: Per-criterion integer scores for this hypothesis.

    Returns:
        A single review-entry dict in the batch ``reviews`` shape.
    """
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
    """Stub review's LLM to return one batch entry per given score dict."""
    stub_call_llm_json(
        monkeypatch,
        review,
        {"reviews": [_batch_entry(scores) for scores in score_dicts]},
    )


def _assert_batch_review(
    hyp: Any, overall: float, scores: dict[str, int]
) -> None:
    """Assert a hypothesis got one batch review with the expected values."""
    assert len(hyp.reviews) == 1
    rev = hyp.reviews[0]
    assert rev.overall_score == pytest.approx(overall)
    assert rev.review_summary == "batch summary"
    # scores flow through verbatim, keyed to the matching batch entry.
    assert rev.scores == scores
    assert rev.safety_ethical_concerns == "none noted"
    assert rev.constructive_feedback == "tighten the experiment"
    # Node mirrors the review's overall_score onto the hypothesis score.
    assert hyp.score == pytest.approx(overall)


async def test_review_node_gates_on_the_run_criteria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scientist's criteria govern the node's gate decision (K4).

    Every axis scores strongly except testability, which is fatally weak:
    with a testability criterion the run blocks the idea, and the same
    scores without criteria keep the historical soundness/novelty gate,
    which passes it.
    """
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
    """A small batch (<= threshold) is reviewed via one comparative call.

    Three hypotheses sit below ``COMPARATIVE_BATCH_THRESHOLD`` (5), so the
    comparative-batch path runs. The stub returns one entry per hypothesis;
    each hypothesis gets that entry's review with overall_score == mean(scores).
    """
    hyps = [make_hypothesis(text=f"h{i}") for i in range(3)]
    assert len(hyps) <= COMPARATIVE_BATCH_THRESHOLD
    expected_scores = [
        {"soundness": 8, "novelty": 6},  # mean 7.0
        {"soundness": 4, "novelty": 6},  # mean 5.0
        {"soundness": 9, "novelty": 9},  # mean 9.0
    ]
    _stub_batch(monkeypatch, expected_scores)

    result = await review_node(state=make_state(hypotheses=hyps))

    returned = result["hypotheses"]
    assert len(returned) == 3
    # The comparative-batch strategy ran (and exactly one LLM call was made).
    assert result["messages"][0]["metadata"]["strategy"] == "comparative batch"
    assert result["metrics"].llm_calls == 1
    assert result["metrics"].reviews_count == 3
    # Each hypothesis received exactly one review with parsed fields.
    for hyp, overall, scores in zip(
        returned, [7.0, 5.0, 9.0], expected_scores, strict=True
    ):
        _assert_batch_review(hyp, overall, scores)


async def test_parallel_individual_attaches_reviews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A large batch (> threshold) is reviewed via parallel individual calls.

    Six hypotheses exceed ``COMPARATIVE_BATCH_THRESHOLD`` (5), so the
    parallel-individual path runs (one call per hypothesis). The stub returns
    the same flat review dict for every call; overall_score == mean(scores).
    """
    count = COMPARATIVE_BATCH_THRESHOLD + 1  # 6 -> exceeds the threshold
    hyps = [make_hypothesis(text=f"h{i}") for i in range(count)]
    stub_call_llm_json(
        monkeypatch,
        review,
        {
            "review_summary": "individual summary",
            "scores": {"soundness": 7, "novelty": 5},  # mean 6.0
            "safety_ethical_concerns": "no concerns",
            "detailed_feedback": {"relevance": "strong"},
            "constructive_feedback": "add controls",
        },
    )

    result = await review_node(state=make_state(hypotheses=hyps))

    returned = result["hypotheses"]
    assert len(returned) == count
    # The parallel strategy ran with one LLM call per hypothesis.
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
    """The individual path falls back to ``overall_score`` when scores empty.

    With an empty ``scores`` dict, ``review_single_hypothesis`` does not compute
    a mean; it uses ``response.get("overall_score", 0.0)`` instead. Six
    hypotheses route through this individual path.
    """
    count = COMPARATIVE_BATCH_THRESHOLD + 1  # 6 -> parallel individual path
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
    """Zero hypotheses skip review entirely (nothing is unreviewed).

    With no unreviewed hypotheses there is no LLM work to do; the node
    returns an empty hypothesis list without calling the LLM or raising.
    """

    async def fail(**_: Any) -> dict[str, Any]:
        raise AssertionError("no LLM call expected for an empty pool")

    monkeypatch.setattr(review, "call_llm_json", fail)

    result = await review_node(state=make_state(hypotheses=[]))

    assert result["hypotheses"] == []
    assert result["messages"][0]["metadata"]["strategy"] == "skipped"


async def test_second_invocation_reviews_only_new_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-invoking review on a grown pool only calls the LLM for new items.

    Evolution appends immutable children without shrinking the pool, so the
    node must review incrementally: a second invocation with one new
    unreviewed hypothesis issues exactly one review call (not one per pool
    member), and the previously reviewed hypotheses keep their single review.
    """
    calls: list[dict[str, Any]] = []

    async def counting_stub(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        count = kwargs["options"].prompt_metadata["hypotheses_count"]
        return {
            "reviews": [_batch_entry({"soundness": 6}) for _ in range(count)]
        }

    monkeypatch.setattr(review, "call_llm_json", counting_stub)

    hyps = [make_hypothesis(text=f"h{i}") for i in range(3)]
    first = await review_node(state=make_state(hypotheses=hyps))
    assert len(calls) == 1
    assert first["metrics"].reviews_count == 3

    # The pool grows by one unreviewed hypothesis (e.g. an evolved child).
    hyps.append(make_hypothesis(text="child"))
    second = await review_node(state=make_state(hypotheses=hyps))

    # One comparative-batch call covering only the single new hypothesis.
    assert len(calls) == 2
    assert calls[1]["options"].prompt_metadata["hypotheses_count"] == 1
    assert second["metrics"].reviews_count == 1
    # Previously reviewed hypotheses were not re-reviewed; the new one was.
    assert [len(h.reviews) for h in second["hypotheses"]] == [1, 1, 1, 1]


def _entry(index: int | None, summary: str) -> dict[str, Any]:
    """Build one batch-review entry naming its hypothesis by number."""
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


# --- schema bounds -----------------------------------------------------------


def test_score_fields_are_bounded_to_the_rubric_range() -> None:
    """Both review schemas bound every criterion to the rubric's range.

    The prompts hand the model a 1-10 rubric and the initial review
    gate's thresholds are calibrated on those bands; unbounded integer
    fields let a runaway score reach the gate unchallenged (audit E15).
    """
    batch_items = REVIEW_BATCH_SCHEMA["schema"]["properties"]["reviews"][
        "items"
    ]
    for schema in (REVIEW_SCHEMA["schema"], batch_items):
        scores = schema["properties"]["scores"]["properties"]
        for criterion, field in scores.items():
            assert field["minimum"] == REVIEW_SCORE_MINIMUM, criterion
            assert field["maximum"] == REVIEW_SCORE_MAXIMUM, criterion


def test_novelty_review_schema_carries_the_published_two_lists() -> None:
    """Both review schemas carry Google's published novelty-review lists.

    The published exemplar (docs/CORPUS-EXTRACTION.md,
    reviews/als-reflection-reviews.md -- 106 lines, sha256 2f486c549886,
    Figure A.11) prints a complete novelty review as two named lists,
    "Aspects already explored:" and "Novel Aspects:" -- no schema field
    distinguished them before this (MO-3).
    """
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
    """`_review_from_response` carries the two lists onto HypothesisReview."""
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
    """A missing/non-dict novelty_review (json_object downgrade) is safe."""
    review = _review_from_response({"review_summary": "s", "scores": {}})
    assert review.already_explored == []
    assert review.novel_aspects == []

    review = _review_from_response(
        {"review_summary": "s", "scores": {}, "novelty_review": "oops"}
    )
    assert review.already_explored == []
    assert review.novel_aspects == []


def test_batch_schema_identifies_by_index_and_never_echoes_text() -> None:
    """Entries name their hypothesis by prompt number, never by text.

    Echoing the hypothesis text back scales the response with the batch
    size -- the overrun that broke proximity deduplication (audit H3).
    """
    items = REVIEW_BATCH_SCHEMA["schema"]["properties"]["reviews"]["items"]
    assert "hypothesis_index" in items["properties"]
    assert "hypothesis_text" not in items["properties"]


# --- parse-time score validation ---------------------------------------------


def test_out_of_range_scores_are_dropped_not_clamped() -> None:
    """Invalid values vanish; the gate reads them as neutral, not worst.

    Clamping a schema violation onto the rubric floor would let a parse
    defect masquerade as the worst possible review and disqualify the
    idea -- the exact missing-score regression the gate guards against.
    """
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
    """Rubric-valid integers survive; integral floats are rounded."""
    assert _sanitize_review_scores({"novelty": 7, "clarity": 8.0}) == {
        "novelty": 7,
        "clarity": 8,
    }


# --- index-based association ---------------------------------------------


def test_entries_match_by_hypothesis_index_not_list_order() -> None:
    """A response whose entries arrive out of order still maps correctly."""
    entries = [_entry(3, "third"), _entry(1, "first"), _entry(2, "second")]
    matched = _match_batch_entries_to_hypotheses(entries, 3)
    assert [entry["review_summary"] for entry in matched] == [
        "first",
        "second",
        "third",
    ]


def test_entries_without_indices_fall_back_to_list_order() -> None:
    """An index-less response aligns by position, as before the fix."""
    entries = [_entry(None, "a"), _entry(None, "b")]
    matched = _match_batch_entries_to_hypotheses(entries, 2)
    assert [entry["review_summary"] for entry in matched] == ["a", "b"]


def test_invalid_and_duplicate_indices_fall_back_positionally() -> None:
    """Out-of-range and duplicated numbers never claim a hypothesis.

    The two invalid entries fill the slots no valid entry claimed, in
    list order; the surplus entry is dropped rather than overflowing.
    """
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


# --- per-hypothesis isolation ---------------------------------------------


async def test_one_malformed_entry_does_not_abort_the_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A garbage entry fails its hypothesis alone; the rest applies.

    Before the fix a single unparseable entry raised out of the batch
    parse (or failed the whole node on the placeholder validation),
    discarding every valid review alongside it.
    """
    stub_call_llm_json(
        monkeypatch,
        review,
        {"reviews": [_entry(3, "third"), "garbage", _entry(1, "first")]},
    )
    hyps = [make_hypothesis(text=f"h{i}") for i in range(3)]

    result = await review_node(state=make_state(hypotheses=hyps))

    returned = result["hypotheses"]
    # Entries 1 and 3 mapped by their numbers; the garbage entry landed
    # on hypothesis 2 and failed there alone.
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
    """A failed review leaves no trace, so the next pass reviews it again.

    Attaching a placeholder instead would mark the hypothesis reviewed
    forever and let it reach the tournament scored 0.0.
    """
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

    # Only the still-unreviewed hypothesis was sent to the LLM again.
    assert second["metrics"].reviews_count == 1
    assert [h.reviews[-1].review_summary for h in second["hypotheses"]] == [
        "first",
        "second chance",
    ]


async def test_parallel_individual_isolates_a_failed_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One raising individual call no longer aborts the whole batch."""

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
    count = COMPARATIVE_BATCH_THRESHOLD + 1  # parallel individual path
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
    """The empty-rows fallback counts every review failed, no raise.

    A wedged batch must not wedge the run: the node still returns.
    """
    stub_call_llm_json(monkeypatch, review, {"reviews": []})
    hyps = [make_hypothesis(text=f"h{i}") for i in range(3)]

    result = await review_node(state=make_state(hypotheses=hyps))

    assert result["metrics"].reviews_count == 0
    assert result["messages"][0]["metadata"]["review_failures"] == 3
    assert all(not h.reviews for h in result["hypotheses"])


def _blocked(index: int) -> Hypothesis:
    """An idea the initial review gate barred from the tournament."""
    hypothesis = make_hypothesis(
        text=f"blocked idea {index}",
        reviews=[make_review(scores={"scientific_soundness": 2, "novelty": 8})],
    )
    hypothesis.review_disposition = "inaccurate"
    return hypothesis


def _viable(index: int) -> Hypothesis:
    """An idea the initial review gate cleared."""
    hypothesis = make_hypothesis(text=f"viable idea {index}")
    hypothesis.review_disposition = "viable"
    return hypothesis


def _incident_pool() -> list[Hypothesis]:
    """The production pool shape: 20 of 22 ideas blocked by one screen."""
    return [_blocked(i) for i in range(20)] + [_viable(i) for i in range(2)]


class _ReviewStub:
    """Counts mature-review calls per (review type, hypothesis).

    Scoped per hypothesis because the recheck and the cascade's own
    recurrent review are the same review type: an idea a recheck cleared
    earns a genuine recurrent review on a later cycle, and counting the
    two together would read as the recheck re-firing.
    """

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
        """How many recheck calls these hypotheses received."""
        return sum(
            self.calls[(RECHECK_REVIEW_TYPE.value, hypothesis.id)]
            for hypothesis in hypotheses
        )


def _stub_reviews(
    monkeypatch: pytest.MonkeyPatch, verdict: str | None
) -> _ReviewStub:
    """Replace the one seam every mature review call goes through."""
    stub = _ReviewStub(verdict)
    monkeypatch.setattr(comprehensive_reflection, "review_hypothesis", stub)
    return stub


def _state(hypotheses: list[Hypothesis]) -> Any:
    """A state carrying only the pool, so no observation review fires."""
    return make_state(hypotheses=hypotheses, articles_with_reasoning=None)


@pytest.mark.asyncio
async def test_a_recheck_clears_the_ideas_a_deeper_review_finds_sound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 20-of-22 run keeps a real tournament and a real evolution pool."""
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
    """Once per hypothesis per run, not once per cycle."""
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
    """The unbounded case: a recheck that changes nothing must not repeat.

    Blocked ideas are exactly the population that grows when the gate
    misfires, so a recheck driven by the disposition alone would re-fire
    on every cycle for every idea it failed to clear.
    """
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
    """The marker records the attempt, not the answer."""
    pool = [_blocked(0)]
    stub = _stub_reviews(monkeypatch, None)
    state = _state(pool)

    await comprehensive_reflection_node(state)
    await comprehensive_reflection_node(state)

    assert stub.rechecks(pool) == 1


def test_the_recheck_marker_survives_a_checkpoint_round_trip() -> None:
    """A flag held only in memory would re-fire on every run resume."""
    hypothesis = _blocked(0)
    review_recheck.mark_recheck_issued(hypothesis)

    restored = Hypothesis.from_dict(hypothesis.to_dict())

    assert recheck_targets([restored]) == []


def test_the_run_wide_ceiling_bounds_a_pathological_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pool of blocked ideas cannot spend the run's budget on rechecks."""
    monkeypatch.setattr(review_recheck, "MAX_RECHECKS_PER_RUN", 3)
    pool = _incident_pool()

    first = recheck_targets(pool)
    for hypothesis in first:
        review_recheck.mark_recheck_issued(hypothesis)
    second = recheck_targets(pool)

    assert len(first) == 3
    assert second == []


def test_the_gates_this_one_does_not_own_are_left_alone() -> None:
    """Safety, evidence, duplicate and failed-review blocks decide elsewhere."""
    foreign = ["unsafe", "evidence_blocked", "review_failed", "duplicate"]
    pool = []
    for disposition in foreign:
        hypothesis = _blocked(0)
        hypothesis.review_disposition = disposition
        pool.append(hypothesis)

    assert recheck_targets(pool) == []


def test_an_idea_the_cascade_already_rejected_is_not_rechecked() -> None:
    """A fatal mature verdict short-circuits, so a recheck cannot clear it."""
    hypothesis = _blocked(0)
    hypothesis.enrichments["full"] = {"verdict": "rejected"}

    assert recheck_targets([hypothesis]) == []


def _full_review(verdict: str, **overrides: object) -> dict[str, object]:
    """Build a full-review result carrying the given verdict."""
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
    """Build a simulation-review result carrying the given verdict."""
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
    """A full review that rejects the idea changes the disposition.

    The cascade only reviews ideas the initial gate marked viable; the
    rejected verdict must then bar the idea from the tournament exactly
    like the initial gate's not-viable band (audit E1).
    """
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(hypothesis, ReviewType.FULL, _full_review("rejected"))

    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_a_breaking_simulation_blocks_the_tournament() -> None:
    """A simulation whose mechanism breaks down is a fatal finding."""
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(
        hypothesis,
        ReviewType.SIMULATION,
        _simulation_review("breaks_down"),
    )

    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_a_recurrent_rejection_blocks_like_a_full_review() -> None:
    """Recurrent reviews reuse the full-review schema and its bands."""
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
    """Gate semantics carry over: only fatal findings block.

    ``needs_revision`` stays rankable and publishable -- the same
    asymmetry as the initial review gate -- while partially-held
    simulations are a reservation, not a discard signal.
    """
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(hypothesis, review_type, result)

    assert hypothesis.review_disposition == expected
    assert hypothesis.is_rankable()


def test_a_deeper_review_reverses_the_initial_screen() -> None:
    """A full review finding the idea sound un-blocks it (FIX-4).

    The initial screen is one shallow call and no published listing has it
    at all; the full review asks the same question in depth, so its
    verdict replaces the screen's rather than being unable to reach it.
    """
    hypothesis = make_hypothesis(text="idea", review_disposition="inaccurate")

    _store(hypothesis, ReviewType.FULL, _full_review("sound"))

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


def test_a_narrower_review_does_not_reverse_a_fatal_one() -> None:
    """Reversal is between layers, not within the mature cascade.

    A simulation whose mechanism holds answers a narrower question than
    the correctness a full review rejected, so it asserts no disposition
    and the rejection stands.
    """
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(hypothesis, ReviewType.FULL, _full_review("rejected"))
    _store(hypothesis, ReviewType.SIMULATION, _simulation_review("holds"))

    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_a_fatal_simulation_wins_over_a_revising_full_review() -> None:
    """Both reviews land together; the blocking finding dominates."""
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(hypothesis, ReviewType.FULL, _full_review("needs_revision"))
    _store(
        hypothesis,
        ReviewType.SIMULATION,
        _simulation_review("breaks_down"),
    )

    assert hypothesis.review_disposition == "inaccurate"


def test_store_keeps_the_result_on_the_enrichments() -> None:
    """The write path stores the result exactly as the node always did."""
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")
    result = _full_review("sound")

    _store(hypothesis, ReviewType.FULL, result)

    assert hypothesis.enrichments["full"] == result


def test_summary_projects_verdicts_and_strips_retrieval_bookkeeping() -> None:
    """Downstream prompts read verdicts and findings, not retrieval state."""
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
    """The omit-rather-than-hollow convention of deep verification."""
    assert mature_review_summary(None) is None
    assert mature_review_summary({}) is None
    assert mature_review_summary({"claim_gate": {"decision": "pass"}}) is None


def test_summary_clips_long_prose_fields() -> None:
    """The judge reads this at O(n^2); fields stay bounded."""
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
    """The offline backend fills verdict enums with their first value.

    ``sound`` and ``holds`` are both non-fatal, so deterministic offline
    runs keep whatever disposition the initial gate assigned.
    """
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
    """Each review type's fatal verdict blocks from any starting state."""
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    result = (
        _simulation_review(verdict)
        if review_type is ReviewType.SIMULATION
        else _full_review(verdict)
    )
    _store(hypothesis, review_type, result)

    assert not hypothesis.is_rankable()


def test_go_no_go_recommendation_cannot_gate_the_disposition() -> None:
    """R14-15: the Go/No-Go field is display text, never a decision.

    A ``sound`` full review carrying a contradictory ``No-Go`` framing
    still leaves the hypothesis viable -- ``apply_mature_review_disposition``
    reads only ``verdict``, never ``go_no_go_recommendation``. This is the
    same shape of mistake the never-revisited initial review gate made
    (root AGENTS.md Gotchas): a field that reads like a decision must not
    become one by accident.
    """
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
    """The ranking judge, evolution, and meta-review all read this summary.

    All three read ``mature_review_summary`` rather than the raw
    enrichment, so proving the projection drops ``go_no_go_recommendation``
    and ``time_to_verdict`` covers every downstream reader at the one seam
    they share, without needing a separate test per reader.
    """
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
