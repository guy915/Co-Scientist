"""Run create/list/read endpoints.

The draft-run creation flow (interview merge, config assembly, DRAFT row
persistence, background title and goal-restatement generation) plus the
run list and detail
reads. Split from ``app.runs`` by concern, matching the sibling endpoint
modules (``runs_lifecycle``, ``runs_collections``, ``runs_contrib``).
Unlike those siblings this module carries no router of its own: FastAPI
rejects the empty ``""`` create/list paths on a prefix-less sub-router, so
``app.runs`` registers these handlers directly on ``runs.router`` (in the
original order, keeping ``/demo`` ahead of ``/{run_id}``) and re-exports
every name, remaining the stable import and monkeypatch surface.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import (
    BackgroundTasks,
    HTTPException,
    Query,
    Request,
)

from app import (
    credentials,
    engine_adapter,
    runs_crud_create,
    store,
)
from app.auth import client_id, require_client_scope
from app.execution_policy import (
    CAMPAIGN,
    campaign_model_for_config,
    resolve_execution_policy,
    scoped_execution_policy,
)
from app.goal_restatement import generate_goal_restatement
from app.runs_crud_create import (
    _persist_new_run_for_owner as _persist_new_run_impl,
)
from app.runs_crud_create import _receipt_replay as _receipt_replay
from app.runs_crud_create import _run_setup_documents as _run_setup_documents
from app.runs_crud_resolve import (
    _build_run_config as _build_run_config,
)
from app.runs_crud_resolve import (
    _resolve_byok as _resolve_byok,
)
from app.runs_crud_resolve import (
    _resolve_run_interview as _resolve_run_interview,
)
from app.runs_crud_resolve import (
    _resolve_run_settings as _resolve_run_settings,
)
from app.runs_crud_resolve import (
    _ResolvedRunSettings as _ResolvedRunSettings,
)
from app.runs_models import (
    CreateRunRequest,
    RenameRunRequest,
)
from app.runs_support import _run_or_404
from app.store import RunStatus
from app.title_gen import generate_run_title


def _persist_new_run(  # noqa: PLR0913 -- retain the route module's patch seam.
    req: CreateRunRequest,
    request: Request,
    interview: dict[str, Any] | None,
    resolved: _ResolvedRunSettings,
    execution_policy: str = "standard",
    *,
    conn: sqlite3.Connection | None = None,
) -> store.RunRow:
    """Preserve the original helper signature and bind the same owner scope."""
    return _persist_new_run_impl(
        req,
        request,
        interview,
        resolved,
        execution_policy,
        owner=client_id(request),
        conn=conn,
    )


async def _populate_run_title(
    run_id: str,
    goal: str,
    byok: credentials.ByokCredential | None = None,
    *,
    execution_policy: str | None = None,
) -> None:
    """Generate a run's short session title and persist it (best-effort).

    Runs after the create response as a background task, so the create call
    isn't blocked on a model round-trip. A None result (generation
    unavailable) leaves the title unset and surfaces fall back to a clause of
    the goal. A bring-your-own-key run titles under its own credential.

    Scheduled only for a run that has no title yet, so it never overwrites
    one the run's interview chose (see ``create_run``).

    Args:
        run_id: The run to title.
        goal: The run's research goal.
        byok: The run's credential, when it was created with one.
        execution_policy: Policy captured when the run was created.
    """
    run: store.RunRow | None = None
    if execution_policy is None:
        run = store.get_run(run_id)
        if run is None:
            return
        execution_policy = run.execution_policy
    elif execution_policy == CAMPAIGN:
        run = store.get_run(run_id)
    campaign_model = (
        campaign_model_for_config(run.config)
        if run is not None and execution_policy == CAMPAIGN
        else None
    )
    with (
        scoped_execution_policy(
            execution_policy, campaign_model_name=campaign_model
        ),
        credentials.scoped_byok(byok),
    ):
        title = await generate_run_title(goal)
    if title:
        store.set_run_title(run_id, title)


async def _populate_goal_restatement(
    run_id: str,
    goal: str,
    byok: credentials.ByokCredential | None = None,
    *,
    execution_policy: str | None = None,
) -> None:
    """Generate a run's narrative goal restatement and persist it.

    GOAL-RESTATEMENT-001. Runs after the create response as a background
    task, so create isn't blocked on a model round-trip. Best-effort: a None
    result leaves ``goal_restatement`` unset and the report omits the
    paragraph. A bring-your-own-key run restates under its own credential.

    Unlike titling, this is scheduled for every model-backed run regardless
    of whether the run's interview named it -- the restatement is a distinct
    report artifact, not the run's label.

    Args:
        run_id: The run to restate the goal of.
        goal: The run's research goal.
        byok: The run's credential, when it was created with one.
        execution_policy: Policy captured when the run was created.
    """
    run: store.RunRow | None = None
    if execution_policy is None:
        run = store.get_run(run_id)
        if run is None:
            return
        execution_policy = run.execution_policy
    elif execution_policy == CAMPAIGN:
        run = store.get_run(run_id)
    campaign_model = (
        campaign_model_for_config(run.config)
        if run is not None and execution_policy == CAMPAIGN
        else None
    )
    with (
        scoped_execution_policy(
            execution_policy, campaign_model_name=campaign_model
        ),
        credentials.scoped_byok(byok),
    ):
        restatement = await generate_goal_restatement(goal)
    if restatement:
        store.set_run_goal_restatement(run_id, restatement)


def _apply_post_commit_effects(
    run: store.RunRow,
    req: CreateRunRequest,
    byok: Any,
    background_tasks: BackgroundTasks,
) -> None:
    """Run the effects that only make sense once the run row exists.

    They all need a persisted run id, so none can move ahead of the commit
    the way credential and document resolution do, and all need a real model
    -- offline/keyless runs keep the goal-clause title fallback and no
    restatement. Titling additionally skips a run its interview already
    named: the interview chose that name with the whole conversation in
    view, where generation sees only the goal, so regenerating would
    overwrite the better title with the worse. The restatement carries no
    such fallback, so it is scheduled for every model-backed run.

    Args:
        run: The freshly persisted run row.
        req: The create request, read for the research goal.
        byok: The caller's resolved bring-your-own-key credential, if any.
        background_tasks: Queue used to title the run and synthesize its
            goal restatement off the critical path.
    """
    model_backed = byok is not None or not engine_adapter.offline_mode()
    if run.title is None and model_backed:
        background_tasks.add_task(
            _populate_run_title,
            run.id,
            req.research_goal,
            byok,
            execution_policy=run.execution_policy,
        )
    # GOAL-RESTATEMENT-001: scheduled for every model-backed run (not gated on
    # the title, which the interview may already have supplied), off the
    # create critical path just like titling.
    if model_backed:
        background_tasks.add_task(
            _populate_goal_restatement,
            run.id,
            req.research_goal,
            byok,
            execution_policy=run.execution_policy,
        )


async def create_run(
    req: CreateRunRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Keep the registered endpoint and its patchable post-commit seam."""
    return await runs_crud_create.create_run(
        req,
        request,
        background_tasks,
        runs_crud_create.RunCreationCallbacks(
            require_client_scope=require_client_scope,
            client_id=client_id,
            resolve_execution_policy=resolve_execution_policy,
            scoped_execution_policy=scoped_execution_policy,
            resolve_byok=_resolve_byok,
            resolve_run_interview=_resolve_run_interview,
            resolve_run_settings=_resolve_run_settings,
            persist_new_run=_persist_new_run,
            run_setup_documents=_run_setup_documents,
            post_commit_effects=_apply_post_commit_effects,
        ),
    )


def _runs_payload(runs: list[store.RunRow]) -> dict[str, Any]:
    """Serialize runs with their per-run execution progress attached."""
    # One connection for every per-run progress query instead of opening a
    # fresh SQLite connection per row (up to `limit` of them on a list call).
    with store.connect() as conn:
        return {
            "runs": [
                {
                    **r.to_dict(),
                    "execution_progress": store.task_progress(r.id, conn=conn),
                }
                for r in runs
            ]
        }


async def list_runs(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    """List the requesting client's runs, most recent first.

    An identity-less compatibility caller (no ``X-Client-ID`` header) owns
    nothing -- ``create_run`` refuses that caller a run of its own -- so
    its list is always empty rather than querying a scope that could only
    ever match legacy rows predating that guard.
    """
    subject = client_id(request)
    if not subject:
        return {"runs": []}
    runs = store.list_runs(client_id=subject, limit=limit)
    return _runs_payload(runs)


# app.runs registers this before /{run_id} so the literal path wins route
# matching.
async def list_demo_runs() -> dict[str, Any]:
    """List the seeded demo runs, which are visible to every client."""
    runs = store.list_runs(client_id=store.DEMO_CLIENT_ID)
    return _runs_payload(runs)


async def get_run(run_id: str) -> dict[str, Any]:
    """Return a run's details plus per-table summary counts."""
    # One connection shared across the run lookup and its summary counts.
    with store.connect() as conn:
        run = _run_or_404(run_id, conn=conn)
        summary = store.summary_counts(run_id, conn=conn)
        checkpoint = store.get_latest_checkpoint(run_id, conn=conn)
        if checkpoint and run.status in {
            RunStatus.QUEUED.value,
            RunStatus.RUNNING.value,
            RunStatus.SYNTHESIZING.value,
        }:
            envelope = checkpoint.get("state") or {}
            live_state = envelope.get("state") or {}
            # Checkpointed pools are committed scientific effects even before
            # final publication drains them into report-facing SQL tables.
            summary["hypotheses"] = max(
                summary["hypotheses"], len(live_state.get("hypotheses") or [])
            )
            summary["evidence"] = max(
                summary["evidence"], len(live_state.get("articles") or [])
            )
        progress = store.task_progress(run_id, conn=conn)
        awaiting = _awaiting_decision_count(run, conn=conn)
        failure_kind = None
        if run.status == RunStatus.FAILED.value:
            status_event = store.latest_status_event(run_id, conn=conn)
            if status_event and status_event.get("status") == run.status:
                failure_kind = status_event.get("failure_kind")
    return {
        **run.to_dict(),
        "failure_kind": failure_kind,
        "summary": summary,
        "execution_progress": progress,
        "awaiting_decision_count": awaiting,
    }


def _awaiting_decision_count(
    run: store.RunRow, *, conn: sqlite3.Connection
) -> int:
    """Count unresolved reviewable safety decisions blocking this run.

    Derived, not persisted: a run is "awaiting a person" exactly when it is
    paused *and* carries an unresolved ``requires_review`` decision -- both
    facts already live elsewhere (``runs.status``, ``safety_decisions``), so
    adding a third status value here would just let them disagree. Gated on
    ``paused`` first so every other run (the overwhelming majority) costs
    this endpoint nothing beyond the status check already in hand.
    """
    if run.status != RunStatus.PAUSED.value:
        return 0
    return store.count_unresolved_review_decisions(run.id, conn=conn)


async def rename_run(run_id: str, body: RenameRunRequest) -> dict[str, Any]:
    """Rename an owned run, replacing its existing session title.

    The title is only ever a label: it comes from the run's interview, or
    is generated from the goal after creation when the interview named
    nothing (see ``_populate_run_title``), and is read by the sidebar, the
    run titlebar and the report header -- nothing scientific derives from it.
    Renaming therefore has no run-state precondition -- an active run is
    renameable, and the new name is what its report carries when it lands.

    The research goal is deliberately not editable here. It is the input
    every hypothesis, review and tournament judgment was produced against,
    so rewriting it would leave a run whose record no longer states what it
    actually explored.

    Returns:
        The renamed run's details, in the same shape as ``get_run``.

    Raises:
        HTTPException: 404 if the run does not exist (or is not owned by
            the caller -- ``app.main.enforce_run_ownership`` answers that
            before this handler runs); 403 for a shared demo run, which
            that middleware deliberately exempts from ownership so every
            caller can read it, and which is therefore no one caller's to
            rename (the same guard ``app.runs_deletion`` applies).
    """
    run = _run_or_404(run_id)
    if run.client_id == store.DEMO_CLIENT_ID:
        raise HTTPException(
            status_code=403, detail="the demo run cannot be renamed"
        )
    title = " ".join(body.title.split())
    if not title:
        raise HTTPException(status_code=422, detail="title cannot be blank")
    store.set_run_title(run_id, title)
    return await get_run(run_id)
