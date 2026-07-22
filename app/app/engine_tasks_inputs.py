"""Durable run-input entry points: bootstrap and scientist input.

Enqueues the first task of a node-level engine run, reopens completed
runs for scientist-directed continuation, and merges durable manual
hypotheses and reviews into workflow state at safe task boundaries.
Split from ``app.engine_tasks``, which re-exports these names so it
remains the stable import and monkeypatch surface.
"""

from __future__ import annotations

from typing import Any

from app import store
from app.elo import INITIAL_ELO
from app.engine_tasks_support import BOOTSTRAP_TASK, NODE_TASK_PREFIX
from app.store import RunStatus, ScientificTask


def enqueue_bootstrap(
    run_id: str, *, db_path: str | None = None
) -> ScientificTask:
    """Enqueue the first idempotent task of a node-level engine run."""
    return store.enqueue_task(
        run_id,
        BOOTSTRAP_TASK,
        {},
        idempotency_key="engine:bootstrap:v1",
        priority=100,
        provenance={
            "behavior": "evidence-bounded-reconstruction",
            "scheduler": "durable-specialist-tasks-v1",
        },
        budget={"lease_seconds": 300},
        db_path=db_path,
    )


def enqueue_scientist_continuation(
    run_id: str,
    input_id: int,
    *,
    db_path: str | None = None,
) -> ScientificTask | None:
    """Reopen a completed engine run so new scientist input enters the loop."""
    run = store.get_run(run_id, db_path=db_path)
    if run is None or run.provider != "engine":
        return None
    if run.status != RunStatus.COMPLETED.value:
        return None
    checkpoint = store.get_latest_checkpoint(run_id, db_path=db_path)
    if checkpoint is None:
        return None
    store.update_run_status(run_id, RunStatus.QUEUED, db_path=db_path)
    return store.enqueue_task(
        run_id,
        f"{NODE_TASK_PREFIX}orchestrator",
        {"checkpoint_seq": int(checkpoint["seq"])},
        idempotency_key=f"engine:scientist-continuation:{input_id}",
        priority=100,
        provenance={
            "behavior": "scientist-directed-continuation",
            "input_id": input_id,
        },
        budget={"lease_seconds": 300},
        db_path=db_path,
    )


def _merge_scientist_inputs(
    state: dict[str, Any], run_id: str, db_path: str | None
) -> None:
    """Merge durable manual hypotheses and reviews at a safe task boundary."""
    from co_scientist.models import (
        Hypothesis,
        HypothesisOrigin,
        HypothesisReview,
    )

    hypotheses = list(state.get("hypotheses") or [])
    by_id = {hypothesis.id: hypothesis for hypothesis in hypotheses}
    for row in store.list_hypotheses(run_id, db_path=db_path):
        if row.get("created_by_agent") != "scientist_manual":
            continue
        hypothesis_id = str(row["id"])
        if hypothesis_id in by_id:
            continue
        hypothesis = Hypothesis(
            id=hypothesis_id,
            text=str(row.get("statement") or row.get("title") or ""),
            origin=HypothesisOrigin.SCIENTIST_MANUAL,
            explanation=str(row.get("title") or "") or None,
        )
        hypothesis.elo_rating = int(row.get("elo_rating") or INITIAL_ELO)
        hypotheses.append(hypothesis)
        by_id[hypothesis_id] = hypothesis

    verdict_scores = {"support": 90, "revise": 60, "oppose": 20}
    for row in store.list_reviews(run_id, db_path=db_path):
        if row.get("reviewer_agent") != "scientist":
            continue
        hypothesis = by_id.get(str(row.get("hypothesis_id")))
        if hypothesis is None:
            continue
        marker = f"[scientist-review:{row['id']}]"
        if any(
            marker in review.review_summary for review in hypothesis.reviews
        ):
            continue
        summary = str(row.get("summary") or "")
        verdict = next(
            (value for value in verdict_scores if value in summary.lower()),
            "revise",
        )
        score = verdict_scores[verdict]
        hypothesis.reviews.append(
            HypothesisReview(
                review_summary=f"{marker} {summary}",
                scores={"scientist_assessment": score},
                safety_ethical_concerns="",
                detailed_feedback={
                    "scientist_critique": str(row.get("critique") or "")
                },
                constructive_feedback=str(row.get("critique") or ""),
                overall_score=float(score),
            )
        )
    state["hypotheses"] = hypotheses
