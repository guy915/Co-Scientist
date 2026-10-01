"""Durable run-input entry points: bootstrap and scientist input.

Enqueues the first task of a node-level engine run, reopens completed
runs for scientist-directed continuation, and merges durable manual
hypotheses and reviews into workflow state at safe task boundaries.
Split from ``app.engine_tasks``, which re-exports these names so it
remains the stable import and monkeypatch surface.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app import store
from app.elo import INITIAL_ELO
from app.engine_tasks.support import (
    BOOTSTRAP_TASK,
    NODE_TASK_PREFIX,
    SafetyHoldError,
)
from app.human_input import VERDICT_REVIEW_SCORES
from app.safety import ScreenSubject
from app.store import RunRow, RunStatus, ScientificTask


def enqueue_bootstrap(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> ScientificTask:
    """Enqueue the bootstrap, optionally in its caller's transaction."""
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
        conn=conn,
    )


def _bootstrap_start_status(
    task: ScientificTask, run: RunRow, db_path: str | None
) -> str:
    """Advance run status only while this bootstrap still owns its lease."""
    status = store.mark_bootstrap_running(
        run.id,
        task.id,
        task.lease_owner,
        task.attempt,
        db_path=db_path,
    )
    if status is None:
        from app.task_worker_outcomes import _LeaseLostError

        raise _LeaseLostError(
            f"bootstrap task {task.id} lost its lease before run start"
        )
    return status


async def _screen_bootstrap_intake(
    run: RunRow,
    emit: Any,
    db_path: str | None,
    task: ScientificTask | None,
    *,
    screening: tuple[Any, Any, Any],
) -> dict[str, Any] | None:
    """Run the intake gate with the bootstrap lease as its status fence."""
    screen_with_escalation, screen_intake, apply_safety_gate = screening
    decision = await screen_with_escalation(
        run.id,
        ScreenSubject(
            "intake", run.research_goal, screen_intake(run.research_goal)
        ),
        provider=run.provider,
        db_path=db_path,
    )
    lease_guard = (
        (task.id, task.lease_owner, task.attempt) if task is not None else None
    )
    async for _ in apply_safety_gate(
        run.id,
        decision,
        emit,
        db_path=db_path,
        lease_guard=lease_guard,
        task=task,
    ):
        pass
    if decision.decision == "hold":
        raise SafetyHoldError(f"intake held for review: {decision.reason}")
    if decision.decision == "block":
        return {"run_id": run.id, "status": "withheld", "terminal": True}
    return None


def reopen_for_pending_scientist_input(
    run_id: str, *, db_path: str | None = None
) -> ScientificTask | None:
    """Reopen a just-completed run when scientist input is still unread.

    A contribution (a hypothesis, a review, or a bare steering message --
    every one of them queues a steering message; see
    ``runs_contrib._steer_and_continue``) posted after a run's last
    orchestrator boundary -- e.g. while its final nodes are draining and
    publishing the report -- has nowhere left to land: it is persisted
    and screened, but ``enqueue_scientist_continuation`` only reopens an
    already-``completed`` run, and nothing else would call it again until
    some *later*, unrelated contribution happened to arrive. Calling this
    the moment finalize settles closes that race for the contribution
    that caused it, instead of leaving it stranded on the next one
    (HITL-STEERING-001 / HITL-MANUAL-HYP-001).

    Deliberately keyed on ``get_pending_steering`` alone, not on any
    broader "does this run owe a review" scan: every contribution already
    queues a steering message, so nothing this hook should act on can
    exist without one, and the message empties for good once acknowledged
    -- so this can never re-fire without new, unread input to justify it.

    Returns:
        The enqueued continuation task, or None when there is nothing
        pending (the ordinary case) or the run never reached completed.
    """
    pending = store.get_pending_steering(run_id, db_path=db_path)
    if not pending:
        return None
    return enqueue_scientist_continuation(
        run_id, pending[0].id, db_path=db_path
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
    store.append_event(
        run_id,
        "lifecycle",
        {"event": "reopened_for_scientist_input", "input_id": input_id},
        db_path=db_path,
    )
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


# Where the author rides through the checkpoint. The engine's Hypothesis
# has no author field and adding one would touch every node; enrichments is
# the established home for a checkpointed per-hypothesis mark (see
# ``review_recheck_issued``), and nothing renders the whole dict into a
# prompt, so the attribution travels without leaking into model input.
SCIENTIST_AUTHOR_MARK = "scientist_author"

# The column's own default, meaning "no screen has run on this row yet"
# (``store/schema.py``). It must not be carried into engine state, because
# there a *non-None* ``safety_status`` means "already screened, leave it"
# (``agents/safety/safety_screen._screen_one_hypothesis``): copying the
# placeholder across would tell the engine's screen to skip exactly the
# hypothesis whose screen never completed.
_UNSCREENED_SAFETY_STATUS = "pending"


def _admitted_safety_status(row: dict[str, Any]) -> str | None:
    """The screened outcome to carry into engine state, or None."""
    status = str(row.get("safety_status") or "")
    if not status or status == _UNSCREENED_SAFETY_STATUS:
        return None
    return status


def _admitted_hypothesis(row: dict[str, Any]) -> Any:
    """Build the engine hypothesis one persisted scientist row becomes.

    Carries the row's own provenance rather than a bare statement: the
    origin the tournament and the drain attribute it by, the author, and
    the outcome the admission screen already wrote (POST time,
    ``hypothesis_screening.screen_hypotheses``) so engine state agrees
    with the store instead of re-screening what is already decided -- but
    never the unscreened placeholder, which would suppress the screen
    rather than record one.
    """
    from co_scientist.models import Hypothesis, HypothesisOrigin

    hypothesis = Hypothesis(
        id=str(row["id"]),
        text=str(row.get("statement") or row.get("title") or ""),
        origin=HypothesisOrigin.SCIENTIST_MANUAL,
        explanation=str(row.get("title") or "") or None,
    )
    hypothesis.elo_rating = int(row.get("elo_rating") or INITIAL_ELO)
    hypothesis.safety_status = _admitted_safety_status(row)
    hypothesis.enrichments[SCIENTIST_AUTHOR_MARK] = str(row.get("author") or "")
    return hypothesis


def _merge_scientist_hypotheses(
    hypotheses: list[Any],
    by_id: dict[str, Any],
    run_id: str,
    db_path: str | None,
) -> None:
    """Append durable scientist-authored hypotheses not yet in state."""
    for row in store.list_hypotheses(run_id, db_path=db_path):
        if row.get("created_by_agent") != "scientist_manual":
            continue
        hypothesis_id = str(row["id"])
        if hypothesis_id in by_id:
            continue
        hypothesis = _admitted_hypothesis(row)
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
    ``drain.reviews._persist_scientist_review``).
    """
    from co_scientist.models import SCIENTIST_REVIEWER, HypothesisReview

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
        # Typed authorship, not a marker to be recovered from prose: the
        # review gate reads the verdict as a whole (a human review scores
        # no gated axis), while the review node, the durable review
        # fan-out and the scheduler's unreviewed backlog must all keep
        # counting the idea as still owing the run a peer review.
        reviewer=SCIENTIST_REVIEWER,
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
    state: dict[str, Any],
    run_id: str,
    db_path: str | None,
    *,
    admit_hypotheses: bool = True,
) -> None:
    """Merge durable manual hypotheses and reviews at a safe task boundary.

    Reviews merge at every boundary: a verdict only ever restricts or
    redirects the pool that is already there, and re-deriving the
    dispositions from it costs no LLM call.

    A *hypothesis* is a new competitor, so it is admitted at one boundary
    (``admit_hypotheses``; see ``engine_tasks.restore``) rather than
    wherever the run happens to be. The pool may not grow inside a ranking
    wave, where the newcomer's Elo would mean nothing, nor between a
    fan-out's items and its aggregate, where the aggregate restores the
    checkpoint and would not find the hypothesis its item reviewed.
    """
    hypotheses = list(state.get("hypotheses") or [])
    by_id = {hypothesis.id: hypothesis for hypothesis in hypotheses}
    if admit_hypotheses:
        _merge_scientist_hypotheses(hypotheses, by_id, run_id, db_path)
    _merge_scientist_reviews(by_id, run_id, db_path)
    state["hypotheses"] = hypotheses
    _refresh_dispositions(hypotheses, state)


def _refresh_dispositions(hypotheses: list[Any], state: dict[str, Any]) -> None:
    """Re-derive dispositions so a merged verdict reaches the next node.

    Without this a contributed review would only take effect at the next
    review pass, and a run past its last one would never read it at all.
    It reads reviews already paid for and spends nothing.
    """
    from co_scientist.agents.reflection.review_gate import (
        refresh_review_dispositions,
    )

    refresh_review_dispositions(hypotheses, state.get("criteria"))
