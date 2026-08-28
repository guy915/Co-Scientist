"""Batch-review robustness: schema bounds, index association, isolation.

Finding E15: the comparative batch review had no rubric bounds on its
score fields, associated results to hypotheses by list order, and let a
single malformed result abort the whole batch. These tests pin the fix:

- scores are bounded to the rubric's integer range in the schema and
  validated (dropped, not clamped) at parse time;
- entries are matched back to hypotheses by the ``hypothesis_index``
  the prompt assigned, with list order only as the fallback for entries
  whose index is absent, invalid, or duplicated;
- one malformed entry (or one failed individual call) is recorded as a
  failure for its hypothesis while the rest of the batch applies.
"""

from collections.abc import Iterator
from typing import Any

import pytest

from co_scientist.agents.reflection import review
from co_scientist.agents.reflection.review import review_node
from co_scientist.agents.reflection.review_helpers import (
    _match_batch_entries_to_hypotheses,
    _review_from_response,
    _sanitize_review_scores,
)
from co_scientist.constants import COMPARATIVE_BATCH_THRESHOLD
from co_scientist.schemas.review import (
    REVIEW_BATCH_SCHEMA,
    REVIEW_SCHEMA,
    REVIEW_SCORE_MAXIMUM,
    REVIEW_SCORE_MINIMUM,
)
from tests._llm_fake import stub_call_llm_json
from tests._state import make_hypothesis, make_state


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
