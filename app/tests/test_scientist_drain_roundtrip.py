"""Scientist contributions surviving the engine final-state drain.

A scientist-contributed hypothesis and review are persisted at POST time,
merged into engine state at the next task boundary, and then drained back
out with the rest of the final state. These tests pin what that round trip
must preserve: the hypothesis's own row (id, author, provenance, lineage,
safety state) rather than a colliding second insert, and the review's
authorship and verdict rather than a generic re-attributed copy.
"""

from __future__ import annotations

from typing import Any

from app import engine_tasks, store
from tests._drain_helpers import _persist


def _seed_scientist_hypothesis(run_id: str, db_path: str) -> str:
    """Persist a scientist-contributed hypothesis the way the endpoint does."""
    return store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="Scientist idea",
            statement="A scientist-proposed mechanism for kinase X.",
            created_by_agent="scientist_manual",
            author="dr-who",
        ),
        db_path=db_path,
    )


def _seed_scientist_review(
    run_id: str, hypothesis_id: str, db_path: str
) -> None:
    """Persist a scientist review the way the endpoint does."""
    store.add_review(
        store.NewReview(
            run_id=run_id,
            hypothesis_id=hypothesis_id,
            reviewer_agent="scientist",
            summary="Scientist verdict: oppose (by dr-who)",
            critique="The proposed control cannot distinguish the mechanism.",
            author="dr-who",
            verdict="oppose",
        ),
        db_path=db_path,
    )


def _merged_final_state(run_id: str, db_path: str) -> dict[str, Any]:
    """Merge the run's scientist input and shape it as a drained final state."""
    state: dict[str, Any] = {"hypotheses": []}
    engine_tasks._merge_scientist_inputs(state, run_id, db_path)
    return {
        "hypotheses": [h.to_dict() for h in state["hypotheses"]],
        "articles": [],
        "tournament_matchups": [],
        "proximity_graph": {},
        "meta_review": {},
        "research_overview": {},
    }


def _replay_finalize(
    run_id: str, final_state: dict[str, Any], db_path: str
) -> None:
    """Run the finalizer's publication reset and drain, as its task does."""
    store.clear_publication_artifacts(run_id, db_path=db_path)
    _persist(run_id=run_id, final_state=final_state, db_path=db_path)


def test_drained_scientist_hypothesis_keeps_its_row(isolated_db: str) -> None:
    """The scientist's own row is preserved, not re-inserted into a collision.

    The row survives the finalizer's publication reset by design, so the
    drain meets an id it already stored and must reconcile with it rather
    than insert a duplicate.
    """
    run = store.create_run("Scientist drain", "express", "engine", {})
    hypothesis_id = _seed_scientist_hypothesis(run.id, isolated_db)
    final_state = _merged_final_state(run.id, isolated_db)

    _replay_finalize(run.id, final_state, isolated_db)

    rows = store.list_hypotheses(run.id, isolated_db)
    assert [row["id"] for row in rows] == [hypothesis_id]
    assert rows[0]["author"] == "dr-who"
    assert rows[0]["created_by_agent"] == "scientist_manual"
    assert rows[0]["generation"] == 0
    assert rows[0]["parent_id"] is None
    assert rows[0]["safety_status"] is not None


def test_drained_scientist_hypothesis_keeps_tournament_counts(
    isolated_db: str,
) -> None:
    """Replaying the finalizer does not accumulate the row's win/loss counts."""
    run = store.create_run("Scientist replay", "express", "engine", {})
    _seed_scientist_hypothesis(run.id, isolated_db)
    final_state = _merged_final_state(run.id, isolated_db)
    final_state["hypotheses"][0]["win_count"] = 3
    final_state["hypotheses"][0]["loss_count"] = 1

    _replay_finalize(run.id, final_state, isolated_db)
    _replay_finalize(run.id, final_state, isolated_db)

    rows = store.list_hypotheses(run.id, isolated_db)
    assert (rows[0]["win_count"], rows[0]["loss_count"]) == (3, 1)


def test_drained_scientist_review_keeps_author_and_verdict(
    isolated_db: str,
) -> None:
    """The review stays attributed to its author, not relabeled 'review'."""
    run = store.create_run("Scientist review drain", "express", "engine", {})
    hypothesis_id = _seed_scientist_hypothesis(run.id, isolated_db)
    _seed_scientist_review(run.id, hypothesis_id, isolated_db)
    final_state = _merged_final_state(run.id, isolated_db)

    _replay_finalize(run.id, final_state, isolated_db)

    reviews = store.list_reviews(run.id, isolated_db)
    assert [row["reviewer_agent"] for row in reviews] == ["scientist"]
    assert reviews[0]["author"] == "dr-who"
    assert reviews[0]["verdict"] == "oppose"


def test_scientist_review_score_uses_the_engine_review_rubric(
    isolated_db: str,
) -> None:
    """A scientist verdict scores on the same 1-10 scale as agent reviews.

    The score is read from the persisted verdict, not guessed from words in
    the summary prose, and lands in the rubric band the verdict means -- the
    ranking prompt renders it beside agent scores, so an off-scale value
    (the old 20/60/90) misrepresents the idea to the judge.
    """
    from co_scientist.constants import NEEDS_REVISION_SCORE, NOT_VIABLE_SCORE

    run = store.create_run("Scientist rubric", "express", "engine", {})
    hypothesis_id = _seed_scientist_hypothesis(run.id, isolated_db)
    _seed_scientist_review(run.id, hypothesis_id, isolated_db)
    state: dict[str, Any] = {"hypotheses": []}

    engine_tasks._merge_scientist_inputs(state, run.id, isolated_db)

    review = state["hypotheses"][0].reviews[0]
    assert review.overall_score == NOT_VIABLE_SCORE
    assert review.overall_score <= NEEDS_REVISION_SCORE
    assert review.detailed_feedback["scientist_author"] == "dr-who"
    assert review.detailed_feedback["scientist_verdict"] == "oppose"
