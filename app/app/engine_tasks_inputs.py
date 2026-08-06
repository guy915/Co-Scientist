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
from app.human_input import VERDICT_REVIEW_SCORES
from app.store import RunStatus, ScientificTask


def enqueue_bootstrap(
    run_id: str, *, db_path: str | None = None
) -> ScientificTask:
    """Enqueue the first idempotent task of a node-level engine run."""
    return store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=BOOTSTRAP_TASK,
            inputs={},
            idempotency_key="engine:bootstrap:v1",
            priority=100,
            provenance={
                "behavior": "evidence-bounded-reconstruction",
                "scheduler": "durable-specialist-tasks-v1",
            },
            budget={"lease_seconds": 300},
        ),
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
        store.NewTask(
            run_id=run_id,
            task_type=f"{NODE_TASK_PREFIX}orchestrator",
            inputs={"checkpoint_seq": int(checkpoint["seq"])},
            idempotency_key=f"engine:scientist-continuation:{input_id}",
            priority=100,
            provenance={
                "behavior": "scientist-directed-continuation",
                "input_id": input_id,
            },
            budget={"lease_seconds": 300},
        ),
        db_path=db_path,
    )


def _merge_scientist_hypotheses(
    hypotheses: list[Any],
    by_id: dict[str, Any],
    run_id: str,
    db_path: str | None,
) -> None:
    """Append durable scientist-authored hypotheses not yet in state."""
    from co_scientist.models import Hypothesis, HypothesisOrigin

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


def _row_verdict(row: dict[str, Any]) -> str:
    """Return a scientist review row's verdict.

    Reads the stored ``verdict`` column. Rows written before that column
    existed carry the verdict only inside their summary prose, so those fall
    back to the original word scan; "revise" is the neutral landing for a
    row whose verdict cannot be recovered either way, because it neither
    endorses nor condemns the idea.
    """
    verdict = str(row.get("verdict") or "").strip().lower()
    if verdict in VERDICT_REVIEW_SCORES:
        return verdict
    summary = str(row.get("summary") or "").lower()
    return next(
        (value for value in VERDICT_REVIEW_SCORES if value in summary),
        "revise",
    )


def _scientist_hypothesis_review(row: dict[str, Any]) -> Any:
    """Build the engine-side review for one persisted scientist review row.

    Authorship, the verdict, and the source row id ride in
    ``detailed_feedback`` because the engine's ``HypothesisReview`` has no
    fields for them -- which is why a human review used to come back out of
    the drain as an anonymous agent review. The drain reads them back (see
    ``drain_reviews._persist_scientist_review``).
    """
    from co_scientist.models import HypothesisReview

    verdict = _row_verdict(row)
    score = VERDICT_REVIEW_SCORES[verdict]
    critique = str(row.get("critique") or "")
    summary = str(row.get("summary") or "")
    return HypothesisReview(
        review_summary=f"{_review_marker(row)} {summary}",
        scores={"scientist_assessment": score},
        safety_ethical_concerns="",
        detailed_feedback={
            "scientist_critique": critique,
            "scientist_author": str(row.get("author") or ""),
            "scientist_verdict": verdict,
            "scientist_review_id": str(row["id"]),
        },
        constructive_feedback=critique,
        overall_score=float(score),
    )


def _review_marker(row: dict[str, Any]) -> str:
    """Return the summary marker identifying a merged scientist review."""
    return f"[scientist-review:{row['id']}]"


def _merge_scientist_reviews(
    by_id: dict[str, Any],
    run_id: str,
    db_path: str | None,
) -> None:
    """Append durable scientist reviews not yet reflected on the hypothesis."""
    for row in store.list_reviews(run_id, db_path=db_path):
        if row.get("reviewer_agent") != "scientist":
            continue
        hypothesis = by_id.get(str(row.get("hypothesis_id")))
        if hypothesis is None:
            continue
        marker = _review_marker(row)
        if any(
            marker in review.review_summary for review in hypothesis.reviews
        ):
            continue
        hypothesis.reviews.append(_scientist_hypothesis_review(row))


def _merge_scientist_inputs(
    state: dict[str, Any], run_id: str, db_path: str | None
) -> None:
    """Merge durable manual hypotheses and reviews at a safe task boundary."""
    hypotheses = list(state.get("hypotheses") or [])
    by_id = {hypothesis.id: hypothesis for hypothesis in hypotheses}
    _merge_scientist_hypotheses(hypotheses, by_id, run_id, db_path)
    _merge_scientist_reviews(by_id, run_id, db_path)
    state["hypotheses"] = hypotheses
