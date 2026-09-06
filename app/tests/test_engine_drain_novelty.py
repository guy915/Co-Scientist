"""Drain persistence of ``hypothesis_state.novelty_score`` (finding K10).

The column used to be filled from the engine's *overall* score, so it
held a different quantity than its name promised. It now carries the
reviewers' own novelty axis.
"""

from __future__ import annotations

from typing import Any

from app import store
from tests._drain_helpers import _engine_hypothesis, _persist


def _review(novelty: float | None, overall: float) -> dict[str, Any]:
    """One engine review scoring novelty apart from its overall score."""
    scores: dict[str, Any] = {"scientific_soundness": 9}
    if novelty is not None:
        scores["novelty"] = novelty
    return {
        "scores": scores,
        "overall_score": overall,
        "review_summary": "s",
        "constructive_feedback": "c",
    }


def _state(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """A final state whose single hypothesis carries ``reviews``.

    ``score`` is deliberately far from every novelty score so a test
    asserting the persisted value cannot pass on the old behavior by
    coincidence.
    """
    return {
        "hypotheses": [
            _engine_hypothesis(
                "h-1", "A hypothesis.", score=9.0, reviews=reviews
            )
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }


def _persisted_novelty(state: dict[str, Any], db_path: str) -> Any:
    """Drain ``state`` and return the stored novelty score."""
    run = store.create_run("novelty goal", "standard", "engine", {})
    _persist(run_id=run.id, final_state=state, db_path=db_path)
    rows = store.list_hypotheses(run.id, db_path=db_path)
    return rows[0]["novelty_score"]


def test_novelty_score_comes_from_the_reviewers_novelty_axis(
    isolated_db: str,
) -> None:
    """The stored value is the review novelty, not the overall score."""
    novelty = _persisted_novelty(_state([_review(3.0, 9.0)]), isolated_db)
    assert novelty == 3.0


def test_novelty_score_averages_across_reviewers(isolated_db: str) -> None:
    """Several reviewers average, so one outlier cannot define the value."""
    state = _state([_review(2.0, 9.0), _review(4.0, 9.0)])
    assert _persisted_novelty(state, isolated_db) == 3.0


def test_novelty_score_is_unset_when_the_reviewer_omitted_it(
    isolated_db: str,
) -> None:
    """A review without a novelty axis stores nothing.

    The old behavior wrote the overall score here, which is exactly the
    case where a reader would most wrongly trust the column name.
    """
    state = _state([_review(None, 9.0)])
    assert _persisted_novelty(state, isolated_db) is None


def test_novelty_score_is_unset_when_nothing_reviewed_it(
    isolated_db: str,
) -> None:
    """An unreviewed hypothesis stores nothing rather than its score."""
    assert _persisted_novelty(_state([]), isolated_db) is None
