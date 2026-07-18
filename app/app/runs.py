"""Run lifecycle router.

Endpoints:
- POST   /api/runs                        create a draft run
- GET    /api/runs                        list runs (most recent first)
- GET    /api/runs/{id}                   read run + summary counts
- POST   /api/runs/{id}/start             start the workflow (background)
- POST   /api/runs/{id}/cancel            cancel a running workflow
- GET    /api/runs/{id}/events         SSE stream (live + replay from `?after=`)
- GET    /api/runs/{id}/hypotheses        list hypotheses with state + lineage
- GET    /api/runs/{id}/evidence          list retrieved evidence
- GET    /api/runs/{id}/matches           tournament matches
- GET    /api/runs/{id}/reviews           reviewer/meta-review notes
- GET    /api/runs/{id}/safety            safety decisions
- GET    /api/runs/{id}/citations         citation rows w/ classification states
- GET    /api/runs/{id}/claim-evidence     claim-level entailment graph
- POST   /api/runs/{id}/hypotheses        scientist-contributed hypothesis
- POST   /api/runs/{id}/reviews           scientist-contributed review
- POST   /api/runs/{id}/attachments       attach a text document to the corpus
- GET    /api/runs/{id}/attachments/search keyword search the run's corpus
- POST   /api/runs/{id}/pause             cooperative pause (-> resumable)
- POST   /api/runs/{id}/resume            resume from the last checkpoint
- GET    /api/runs/{id}/report            structured report payload (latest)
- GET    /api/runs/{id}/report.md         rendered Markdown report

The router maintains a per-run cancellation event in `_active` (defined in
``runs_registry``). Streams are backed by the persisted event log so they
survive client reconnects and full backend restarts. Request models live in
``runs_models`` and SSE streaming helpers in ``runs_events``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import (
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)

from app import (
    document_ingest,
    engine_adapter,
    engine_tasks,
    human_input,
    qa,
    run_corpus,
    store,
    task_worker,
)
from app.auth import client_id
from app.hypothesis_screening import screen_hypotheses
from app.logging_setup import run_log_context
from app.logs_api import logs_payload
from app.runs_events import _event_stream
from app.runs_models import (
    AskRequest,
    CreateRunRequest,
    HumanAttachmentRequest,
    HumanHypothesisRequest,
    HumanReviewRequest,
    SafetyAdjudicationRequest,
    SendMessageRequest,
    StartRunRequest,
    _build_create_run_config,
)
from app.runs_registry import _active, _active_lock, _RunHandle
from app.store import TERMINAL_STATUSES, RunRow, RunStatus
from app.title_gen import generate_run_title

logger = logging.getLogger(__name__)

# Strong references to detached resume tasks so they are not garbage-collected
# mid-run; each removes itself on completion (see _launch_resume).
_resume_tasks: set[asyncio.Task[None]] = set()
router = APIRouter(prefix="/api/runs", tags=["runs"])

# Per-tier cap on concurrently running runs for one client; heavier tiers get
# a lower ceiling. "advanced" is retained for runs persisted during the
# two-tier period (its envelope matches "ultra").
_MODE_CONCURRENCY_LIMITS = {
    "express": 3,
    "standard": 3,
    "extended": 2,
    "ultra": 1,
    "advanced": 1,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_or_404(run_id: str, conn: sqlite3.Connection | None = None) -> RunRow:
    """Return the run row or raise a 404 for unknown run ids."""
    run = store.get_run(run_id, conn=conn)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


def _require_run(run_id: str) -> None:
    """404 if the run does not exist, without materializing the row.

    Use this for endpoints that only need an existence guard; ``_run_or_404``
    is for the few that read the run row itself.
    """
    if not store.run_exists(run_id):
        raise HTTPException(status_code=404, detail="run not found")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def _populate_run_title(run_id: str, goal: str) -> None:
    """Generate a run's short session title and persist it (best-effort).

    Runs after the create response as a background task, so the create call
    isn't blocked on a model round-trip. A None result (generation
    unavailable) leaves the title unset and surfaces fall back to a clause of
    the goal.

    Args:
        run_id: The run to title.
        goal: The run's research goal.
    """
    title = await generate_run_title(goal)
    if title:
        store.set_run_title(run_id, title)


@router.post("")
async def create_run(
    req: CreateRunRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Create a new run for the requesting client and return it.

    Args:
        req: Request body with the research goal, run mode, and run config.
        request: Incoming HTTP request, used to read the client identifier.
        background_tasks: FastAPI background queue used to generate the run's
            session title off the request's critical path.

    Returns:
        The created run serialized as a dict.
    """
    interview = None
    if req.interview_id:
        interview = store.get_interview(req.interview_id)
        if (
            interview is None
            or interview["client_id"] != client_id(request)
            or interview["status"] != "completed"
        ):
            raise HTTPException(
                status_code=409,
                detail="a completed owned interview is required",
            )
        fields = interview["fields"]
        req = req.model_copy(
            update={
                "research_goal": fields["research_challenge"],
                "requirements": fields["preferences"],
                "attributes": fields["focus_area"],
            }
        )

    # Provider (engine vs mock) is decided at creation from availability;
    # /start can still override it per run via force_provider.
    provider = engine_adapter.select_provider()
    config, focus, tier = _build_create_run_config(req)
    if req.notify_on_completion and req.completion_email:
        config["completion_notification"] = {
            "enabled": True,
            "email": req.completion_email,
        }
    if interview is not None:
        config["interview_id"] = interview["id"]
    run_mode = tier
    # The run is persisted in DRAFT; nothing executes until /start is called.
    run = store.create_run(
        research_goal=req.research_goal,
        profile=run_mode,
        provider=provider,
        config=config,
        client_id=client_id(request),
        title=(interview["fields"].get("title") if interview else None),
    )
    # First entry in the run's event log, so replays show creation metadata.
    store.append_event(
        run.id,
        "lifecycle",
        {
            "event": "created",
            "run_mode": run_mode,
            "provider": provider,
            "focus": focus,
            "tier": tier,
        },
    )
    # Title generation needs a real model, so only when a provider is
    # configured (mock/offline and tests keep the goal-clause fallback).
    if provider == "engine":
        background_tasks.add_task(
            _populate_run_title, run.id, req.research_goal
        )
    return run.to_dict()


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


@router.get("")
async def list_runs(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    """List the requesting client's runs, most recent first."""
    runs = store.list_runs(client_id=client_id(request), limit=limit)
    return _runs_payload(runs)


# Registered before /{run_id} so the literal path wins route matching.
@router.get("/demo")
async def list_demo_runs() -> dict[str, Any]:
    """List the seeded demo runs, which are visible to every client."""
    runs = store.list_runs(client_id=store.DEMO_CLIENT_ID)
    return _runs_payload(runs)


@router.get("/{run_id}")
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
    return {
        **run.to_dict(),
        "summary": summary,
        "execution_progress": progress,
    }


def _mark_workflow_failed(
    run_id: str, handle: _RunHandle, error: Exception
) -> None:
    """Log an unhandled workflow crash and land the run in FAILED status.

    Catch-all so an unexpected workflow crash still lands the run in a
    terminal FAILED state with a status event for the UI.
    """
    logger.exception("workflow failed: %s", error)
    store.update_run_status(run_id, RunStatus.FAILED, error=str(error))
    store.append_event(
        run_id, "status", {"status": "failed", "error": str(error)}
    )
    handle.new_event.set()


async def _run_workflow_task(
    run_id: str,
    research_goal: str,
    config: dict[str, Any],
    force_provider: str | None,
    handle: _RunHandle,
    resume: bool = False,
) -> None:
    """Drive a run's workflow to completion as a background task.

    Args:
        run_id: Identifier of the run to drive.
        research_goal: The run's research goal, passed through to the engine.
        config: The run's resolved configuration.
        force_provider: Optional provider override ('mock' or 'engine').
        handle: The run's registry handle for cancellation/new-event signals.
        resume: When True, the engine restores its persisted WorkflowState and
            continues from the last checkpoint instead of running from the goal.
    """
    with run_log_context(run_id):
        await _drive_workflow(
            run_id, research_goal, config, force_provider, handle, resume
        )


async def _drive_workflow(
    run_id: str,
    research_goal: str,
    config: dict[str, Any],
    force_provider: str | None,
    handle: _RunHandle,
    resume: bool = False,
) -> None:
    """Body of ``_run_workflow_task``, run inside the run's log context."""
    try:
        # The adapter persists each event itself; this loop only pulses
        # new_event so any in-process SSE stream wakes immediately.
        async for _ in engine_adapter.run_workflow(
            run_id=run_id,
            research_goal=research_goal,
            config=config,
            cancelled=handle.cancelled,
            force_provider=force_provider,
            resume=resume,
        ):
            handle.new_event.set()
        # A cooperative pause stopped the workflow at a checkpoint boundary.
        # The workflow normally persists/emits `paused` itself (it consults
        # the registry's pause flag); this fallback covers a provider that
        # stopped on the shared cancel signal without emitting a status, so
        # the run still reads as resumable rather than cancelled.
        if handle.paused and store.has_checkpoint(run_id):
            run = store.get_run(run_id)
            if run and run.status != RunStatus.PAUSED.value:
                store.update_run_status(run_id, RunStatus.PAUSED)
                store.append_event(
                    run_id, "status", {"status": "paused", "detail": "paused"}
                )
    except Exception as e:
        _mark_workflow_failed(run_id, handle, e)
    finally:
        # Always release the active-run slot so the run can be restarted.
        async with _active_lock:
            _active.pop(run_id, None)


def _check_startable(run: RunRow) -> None:
    """Raise 409 if `run` cannot be (re)started in its current status.

    Only draft/failed/blocked/cancelled runs may (re)start; in-progress and
    completed runs 409 rather than double-running.
    """
    if run.status in (
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.SYNTHESIZING,
    ):
        raise HTTPException(status_code=409, detail="run already in progress")
    if run.status == RunStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="run already completed")


async def _reserve_active_slot(run_id: str) -> _RunHandle:
    """Atomically reserve the run's active-run slot, or 409 if already active.

    Guards two concurrent /start requests from both passing the DB status
    check and launching twice.
    """
    async with _active_lock:
        if run_id in _active:
            raise HTTPException(status_code=409, detail="run already active")
        handle = _RunHandle()
        _active[run_id] = handle
    return handle


@router.post("/{run_id}/start")
async def start_run(
    run_id: str, req: StartRunRequest, background: BackgroundTasks
) -> dict[str, Any]:
    """Queue a run and launch its workflow as a background task.

    Args:
        run_id: Path identifier of the run to start.
        req: Request body with optional provider override settings.
        background: FastAPI background task registry for the workflow runner.

    Returns:
        A dict with the run 'id' and its new 'status'.

    Raises:
        HTTPException: If the run is missing, already in progress, already
            completed, or already active.
    """
    run = _run_or_404(run_id)
    _check_startable(run)
    effective_provider = req.force_provider or run.provider
    mode = str(run.profile)
    limit = _MODE_CONCURRENCY_LIMITS.get(mode, 3)
    if not store.reserve_run_capacity(
        run_id,
        profile=mode,
        client_id=run.client_id,
        limit=limit,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"concurrent {mode} run limit reached ({limit})",
        )

    # Real scientific runs are delivered through the durable worker queue.
    # Mock fixtures retain the historical background path and are explicitly
    # excluded from fidelity claims.
    if effective_provider == "engine":
        store.append_event(run_id, "lifecycle", {"event": "queued"})
        task = task_worker.enqueue_run_workflow(run_id, force_provider="engine")
        if os.getenv("COSCIENTIST_EMBEDDED_WORKER", "1") == "1":
            # Local compatibility mode consumes the same durable lease. A
            # production worker service runs ``python -m app.task_worker`` and
            # sets COSCIENTIST_EMBEDDED_WORKER=0 on the API service.
            background.add_task(
                task_worker.run_run_worker_pool_sync,
                run_id,
                f"embedded-api:{os.getpid()}",
            )
        return {"id": run_id, "status": "queued", "task_id": task.id}

    handle = await _reserve_active_slot(run_id)

    # Transition draft -> queued before returning; the runner moves the run
    # to running/synthesizing/terminal states as the workflow progresses.
    store.append_event(run_id, "lifecycle", {"event": "queued"})

    # Returns immediately; FastAPI runs the task after the response is sent.
    background.add_task(
        _run_workflow_task,
        run_id,
        run.research_goal,
        run.config,
        req.force_provider,
        handle,
    )
    return {"id": run_id, "status": "queued"}


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    """Cancel a run, whether or not it has an in-process workflow handle.

    With an active handle, cancellation is cooperative: this only sets the
    handle's event, and the workflow transitions the run to CANCELLED at its
    next checkpoint, so the response says 'cancelling'.

    Without a handle -- a draft that never started, or a run left non-terminal
    by a server restart -- there is no workflow to signal, so any non-terminal
    run is transitioned to CANCELLED here directly and a terminal ``cancelled``
    status event is emitted (mirroring the failed-run path) so open SSE streams
    close. An already-terminal run cannot be cancelled and returns 409.
    """
    run = _run_or_404(run_id)
    async with _active_lock:
        handle = _active.get(run_id)
    if handle:
        handle.cancelled.set()
        store.append_event(run_id, "lifecycle", {"event": "cancel_requested"})
        return {"id": run_id, "status": "cancelling"}
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="run already finished")
    store.cancel_run_tasks(run_id)
    store.update_run_status(run_id, RunStatus.CANCELLED)
    store.append_event(run_id, "status", {"status": "cancelled"})
    return {"id": run_id, "status": "cancelled"}


@router.post("/{run_id}/pause")
async def pause_run(run_id: str) -> dict[str, Any]:
    """Cooperatively pause an active run at its next checkpoint (Milestone 4).

    Like cancel, this only signals the in-flight workflow; it stops at the next
    iteration boundary. A resumable checkpoint is ensured here so the run lands
    in the PAUSED state rather than CANCELLED for every provider — the mock
    also checkpoints per iteration, but the engine provider does not, so
    without this a paused engine run would be an unrecoverable cancel.
    """
    run = _run_or_404(run_id)
    async with _active_lock:
        handle = _active.get(run_id)
    if not handle:
        has_engine_task = any(
            task.task_type.startswith("engine.")
            for task in store.list_tasks(run_id)
        )
        if has_engine_task and run.status in {
            RunStatus.QUEUED.value,
            RunStatus.RUNNING.value,
        }:
            store.pause_run_tasks(run_id)
            store.update_run_status(run_id, RunStatus.PAUSED)
            store.append_event(
                run_id, "lifecycle", {"event": "pause_requested"}
            )
            return {"id": run_id, "status": "paused"}
        raise HTTPException(status_code=404, detail="run is not active")
    _ensure_resumable_checkpoint(run_id, run.provider)
    handle.paused = True
    handle.cancelled.set()
    store.append_event(run_id, "lifecycle", {"event": "pause_requested"})
    return {"id": run_id, "status": "pausing"}


def _ensure_resumable_checkpoint(run_id: str, provider: str) -> None:
    """Persist a minimal envelope checkpoint if the run has none yet.

    Relaunch reads the goal/config from the run row, not the checkpoint, so the
    checkpoint's only job is to mark the run resumable (``has_checkpoint``).
    """
    if store.has_checkpoint(run_id):
        return
    store.save_checkpoint(
        run_id,
        stage="pause",
        schema_version=1,
        last_event_seq=store.latest_event_seq(run_id),
        state={"provider": provider, "reason": "pause"},
    )


def _has_paused_engine_task(run_id: str) -> bool:
    """Return whether the run has a paused engine-provider task queued."""
    return any(
        task.status == "paused" and task.task_type.startswith("engine.")
        for task in store.list_tasks(run_id)
    )


@router.post("/{run_id}/resume")
async def resume_run(run_id: str) -> dict[str, Any]:
    """Resume a paused or interrupted run from its last checkpoint.

    Requires a durable checkpoint (else there is nothing to resume from). The
    run's derived artifacts are cleared and the workflow is relaunched, which
    for the deterministic mock reconstructs identical artifacts from the same
    seed. A completed or actively-running run cannot be resumed.
    """
    run = _run_or_404(run_id)
    if run.status == RunStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail="run already completed")
    if run.status in (RunStatus.RUNNING.value, RunStatus.SYNTHESIZING.value):
        raise HTTPException(status_code=409, detail="run already in progress")
    if not store.has_checkpoint(run_id) and not _has_paused_engine_task(run_id):
        raise HTTPException(status_code=409, detail="run has no checkpoint")
    await _launch_resume(run_id)
    return {"id": run_id, "status": "queued"}


async def _launch_resume(run_id: str) -> None:
    """Relaunch a run's workflow from its last checkpoint on a detached task.

    Shared by the resume endpoint and the startup auto-resume launcher. Two
    resume modes, chosen by the kind of checkpoint on disk:

    - Engine checkpoint (a serialized WorkflowState): a *true* resume. The
      engine restores that state and re-enters at the orchestrator, so
      completed LLM/tool work is not repeated. Derived data is NOT cleared —
      the engine persists artifacts only at the final drain, so a mid-run
      interruption left only events + the checkpoint, and clearing would
      discard the pre-orchestrator events that resume never re-emits.
    - Mock (or envelope) checkpoint: a deterministic re-derive from the run's
      seed. Derived data IS cleared so the replay rebuilds identical artifacts
      without duplicating rows or events.

    A completed run is never relaunched by callers.
    """
    run = _run_or_404(run_id)
    checkpoint = store.get_latest_checkpoint(run_id)
    engine_resume = engine_adapter.is_engine_checkpoint(checkpoint)
    if engine_resume or _has_paused_engine_task(run_id):
        store.update_run_status(run_id, RunStatus.QUEUED)
        store.append_event(
            run_id,
            "status",
            {"status": "resuming", "detail": "from specialist checkpoint"},
        )
        task_worker.enqueue_run_workflow(run_id, resume=True)
        if os.getenv("COSCIENTIST_EMBEDDED_WORKER", "1") == "1":
            task = asyncio.create_task(
                task_worker.run_run_until_idle(
                    run_id, f"embedded-resume:{os.getpid()}"
                )
            )
            _resume_tasks.add(task)
            task.add_done_callback(_resume_tasks.discard)
        return

    handle = await _reserve_active_slot(run_id)
    if not engine_resume:
        store.clear_run_derived_data(run_id)
    store.update_run_status(run_id, RunStatus.QUEUED)
    store.append_event(
        run_id, "status", {"status": "resuming", "detail": "from checkpoint"}
    )
    # Resume runs outside a request scope (also used at startup), so drive it
    # on a detached asyncio task rather than FastAPI BackgroundTasks. Keep a
    # strong reference until it finishes so it is not garbage-collected.
    task = asyncio.create_task(
        _run_workflow_task(
            run_id,
            run.research_goal,
            run.config,
            None,
            handle,
            resume=engine_resume,
        )
    )
    _resume_tasks.add(task)
    task.add_done_callback(_resume_tasks.discard)


async def resume_interrupted_runs(run_ids: list[str]) -> None:
    """Relaunch each resumable interrupted run at startup (Milestone 4).

    Called from the app lifespan after ``reconcile_interrupted_runs`` finds
    runs left non-terminal by a restart that still hold a checkpoint. Skips any
    run that has since completed or is already active.
    """
    for run_id in run_ids:
        run = store.get_run(run_id)
        if run is None or run.status == RunStatus.COMPLETED.value:
            continue
        async with _active_lock:
            if run_id in _active:
                continue
        try:
            await _launch_resume(run_id)
        except HTTPException:
            logger.warning("Could not auto-resume run %s", run_id)


# ---------------------------------------------------------------------------
# SSE events
# ---------------------------------------------------------------------------


@router.get("/{run_id}/events")
async def stream_events(
    run_id: str,
    request: Request,
    after: int = Query(0, ge=0),
    stream: bool = Query(True),
) -> Response:
    """Stream a run's events as Server-Sent Events, or list them as JSON.

    The default (``stream=true``) is the SSE contract the run views
    consume: replay history, then tail live events. ``stream=false``
    returns the persisted event log as a one-shot JSON snapshot for
    consumers that must not hold a connection open (e.g. the workbench
    diagnostics popover).

    Args:
        run_id: Path identifier of the run to stream.
        request: Incoming HTTP request, used to detect client disconnects.
        after: Only return events with a sequence number greater than this.
        stream: When false, return ``{"events": [...]}`` instead of SSE.

    Returns:
        A StreamingResponse that replays history then tails live events,
        or a JSONResponse snapshot when ``stream`` is false.
    """
    run = _run_or_404(run_id)
    if not stream:
        return JSONResponse({"events": store.list_events(run_id, after)})
    return StreamingResponse(
        _event_stream(run_id, request, after, run),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Tells nginx-style proxies not to buffer the stream; without
            # this, events can be held back and delivered in bursts.
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@router.get("/{run_id}/hypotheses")
async def get_hypotheses(run_id: str) -> dict[str, Any]:
    """Return the run's hypotheses with Elo state, lineage, and verification."""
    run = _run_or_404(run_id)
    from app.report_render import _unverified_hypothesis_ids

    hyps = store.list_hypotheses(run_id)
    # Flag ideas without an evidence-supported claim so the UI can badge them
    # "Unverified" (they are ranked and published under the rank-and-publish
    # policy; only contradicted/unsafe ideas are withheld from the report).
    # Mock demo runs are illustrative fixtures, not assessed science, so they
    # are never badged (they carry simulated "insufficient" claim rows that
    # would otherwise flag every idea).
    if run.provider == "mock":
        for hyp in hyps:
            hyp["unverified"] = False
    else:
        unverified = _unverified_hypothesis_ids(run_id, None, hyps)
        for hyp in hyps:
            hyp["unverified"] = str(hyp.get("id")) in unverified
    return {"hypotheses": hyps}


@router.get("/{run_id}/evidence")
async def get_evidence(run_id: str) -> dict[str, Any]:
    """Return the literature evidence retrieved for the run."""
    _require_run(run_id)
    return {"evidence": store.list_evidence(run_id)}


@router.get("/{run_id}/matches")
async def get_matches(run_id: str) -> dict[str, Any]:
    """Return the run's tournament matches with Elo snapshots."""
    _require_run(run_id)
    return {"matches": store.list_matches(run_id)}


@router.get("/{run_id}/proximity")
async def get_proximity(run_id: str) -> dict[str, Any]:
    """Return the persisted weighted idea-proximity landscape."""
    _require_run(run_id)
    return {"proximity": store.list_proximity_edges(run_id)}


@router.get("/{run_id}/reviews")
async def get_reviews(run_id: str) -> dict[str, Any]:
    """Return reviewer and meta-review notes for the run."""
    _require_run(run_id)
    return {"reviews": store.list_reviews(run_id)}


@router.get("/{run_id}/safety")
async def get_safety(run_id: str) -> dict[str, Any]:
    """Return the run's intake/final safety-gate decisions."""
    _require_run(run_id)
    return {"safety": store.list_safety_decisions(run_id)}


@router.post("/{run_id}/safety/{decision_id}/adjudicate")
async def adjudicate_safety(
    run_id: str,
    decision_id: int,
    body: SafetyAdjudicationRequest,
    request: Request,
) -> dict[str, Any]:
    """Resolve one held safety decision and update the run lifecycle."""
    run = _run_or_404(run_id)
    reviewer = client_id(request)
    if not reviewer:
        raise HTTPException(
            status_code=403, detail="an identified reviewer is required"
        )
    resolved = store.resolve_safety_decision(
        run_id, decision_id, body.resolution, reviewer
    )
    if not resolved:
        raise HTTPException(
            status_code=409,
            detail="decision is not reviewable or was already resolved",
        )
    if body.resolution == "rejected":
        store.update_run_status(
            run_id,
            RunStatus.BLOCKED,
            error="Safety reviewer rejected held content.",
        )
    elif run.status == RunStatus.PAUSED.value:
        # Intake holds return to draft; final holds retain a checkpoint and can
        # resume through the ordinary recovery path.
        decisions = store.list_safety_decisions(run_id)
        decision = next(item for item in decisions if item["id"] == decision_id)
        target = (
            RunStatus.DRAFT
            if decision["stage"] == "intake"
            else RunStatus.PAUSED
        )
        store.update_run_status(run_id, target, error=None)
    return {"resolution": body.resolution, "decision_id": decision_id}


@router.get("/{run_id}/citations")
async def get_citations(run_id: str) -> dict[str, Any]:
    """Return the run's citation rows with classification states."""
    _require_run(run_id)
    return {"citations": store.list_citations(run_id)}


@router.get("/{run_id}/metrics")
async def get_metrics(run_id: str) -> dict[str, Any]:
    """Return the run's persisted execution metrics.

    The metrics dict (LLM calls, phase timings, artifact counts) is
    persisted when the workflow finalizes; ``metrics`` is null for runs
    that have not completed a finalize yet.
    """
    _require_run(run_id)
    return {"metrics": store.get_run_metrics(run_id)}


@router.get("/{run_id}/logs")
async def get_run_logs(
    run_id: str,
    after_id: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    min_level: str | None = None,
    q: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Return the run's persisted application log records, oldest-first.

    Run-scoped view of ``GET /api/logs``: same filters and payload shape,
    with ``run_id`` fixed to this run.
    """
    _require_run(run_id)
    return logs_payload(
        after_id=after_id,
        limit=limit,
        min_level=min_level,
        run_id=run_id,
        q=q,
        verbose=verbose,
    )


@router.get("/{run_id}/claim-evidence")
async def get_claim_evidence(run_id: str) -> dict[str, Any]:
    """Return the run's claim-level entailment graph (Milestone 5).

    Each edge is one atomic claim of a hypothesis with its assessed label
    (supports/contradicts/insufficient) and the exact supporting/contradicting
    passages that drove the verdict.
    """
    _require_run(run_id)
    return {"claim_evidence": store.list_claim_evidence(run_id)}


@router.post("/{run_id}/hypotheses")
async def add_human_hypothesis(
    run_id: str, req: HumanHypothesisRequest, request: Request
) -> dict[str, Any]:
    """Admit a scientist-contributed hypothesis (Milestone 7).

    The hypothesis passes the *same* per-hypothesis safety review every
    generated hypothesis does (no bypass for human authorship). If admitted,
    it is persisted with `origin=scientist_manual` and its author, screened by
    the shared safety path (so its `safety_status` is set like any other), and
    thereafter appears in the run's hypotheses. A blocked hypothesis returns
    the admission decision and is not persisted (HTTP 200 with admitted=false).
    """
    _require_run(run_id)
    author = client_id(request) or req.author
    admission = human_input.admit_human_hypothesis(
        text=req.statement, author=author, title=req.title
    )
    if not admission.admitted or admission.hypothesis is None:
        return {"admitted": False, "safety": admission.safety_review.to_dict()}

    hyp = admission.hypothesis
    hyp_id = store.add_hypothesis(
        run_id,
        title=str(hyp["title"]),
        statement=str(hyp["statement"]),
        created_by_agent=human_input.SCIENTIST_MANUAL_ORIGIN,
        author=author,
    )
    # Same safety screen as the pipeline, so the manual hypothesis carries a
    # persisted safety_status and any blocking outcome is audited identically.
    screen_hypotheses(run_id, store.list_hypotheses(run_id))
    message = store.append_message(
        run_id,
        author,
        "Scientist-contributed hypothesis to evaluate in subsequent work: "
        f"{req.statement}",
        "steering",
        meta={"kind": "manual_hypothesis", "hypothesis_id": hyp_id},
    )
    continuation = engine_tasks.enqueue_scientist_continuation(
        run_id, message.id
    )
    store.append_event(
        run_id,
        "scientist.hypothesis",
        {"hypothesis_id": hyp_id, "author": author},
    )
    return {
        "admitted": True,
        "id": hyp_id,
        "author": author,
        "continuation_task_id": continuation.id if continuation else None,
        "safety": admission.safety_review.to_dict(),
    }


@router.post("/{run_id}/reviews")
async def add_human_review(
    run_id: str, req: HumanReviewRequest, request: Request
) -> dict[str, Any]:
    """Persist a scientist-contributed review (Milestone 7).

    The review enters the same reviews table as an agent review, attributed to
    its author with `reviewer_agent=scientist`. The verdict must be one of
    support/oppose/revise, and the reviewed hypothesis must belong to the run
    in the URL (no cross-run or dangling review rows).
    """
    _require_run(run_id)
    hyp = store.get_hypothesis(req.hypothesis_id)
    if hyp is None or hyp.get("run_id") != run_id:
        raise HTTPException(
            status_code=404, detail="hypothesis not found in this run"
        )
    author = client_id(request) or req.author
    try:
        review = human_input.build_human_review(
            hypothesis_id=req.hypothesis_id,
            author=author,
            verdict=req.verdict,
            critique=req.critique,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.add_review(
        run_id,
        hypothesis_id=review.hypothesis_id,
        reviewer_agent="scientist",
        summary=f"Scientist verdict: {review.verdict} (by {review.author})",
        critique=review.critique,
    )
    message = store.append_message(
        run_id,
        author,
        "Scientist review of hypothesis "
        f"{req.hypothesis_id}: verdict={review.verdict}; {review.critique}",
        "steering",
        meta={"kind": "human_review", "hypothesis_id": req.hypothesis_id},
    )
    continuation = engine_tasks.enqueue_scientist_continuation(
        run_id, message.id
    )
    store.append_event(
        run_id,
        "scientist.review",
        {
            "hypothesis_id": req.hypothesis_id,
            "author": author,
            "verdict": review.verdict,
        },
    )
    return {
        "recorded": True,
        "continuation_task_id": continuation.id if continuation else None,
        **review.to_dict(),
    }


@router.post("/{run_id}/attachments")
async def add_attachment(
    run_id: str, req: HumanAttachmentRequest
) -> dict[str, Any]:
    """Attach a scientist-provided text document to a run's corpus (M7).

    Text-only and consent-gated: no binary or archive is accepted (so there is
    no extraction/malware surface), the text is size-capped by the request
    model, and ``consent`` must be true. The document is stored as run-scoped
    evidence marked as an attachment and indexed into the private retrieval
    corpus (``run_corpus``).
    """
    _require_run(run_id)
    if not req.consent:
        raise HTTPException(
            status_code=422, detail="consent is required to index a document"
        )
    ev_id = store.add_evidence(
        run_id,
        req.title,
        source=run_corpus.ATTACHMENT_SOURCE,
        abstract=req.text,
    )
    message = store.append_message(
        run_id,
        "scientist",
        f"Use the private research document '{req.title}' in subsequent work.",
        "steering",
        meta={"kind": "attachment", "evidence_id": ev_id},
    )
    continuation = engine_tasks.enqueue_scientist_continuation(
        run_id, message.id
    )
    return {
        "id": ev_id,
        "indexed": True,
        "continuation_task_id": continuation.id if continuation else None,
    }


@router.post("/{run_id}/attachments/upload")
async def upload_attachment(
    run_id: str,
    request: Request,
    file: Annotated[UploadFile, File()],
    consent: Annotated[bool, Form()],
) -> dict[str, Any]:
    """Extract and index a real scientist-uploaded document with provenance."""
    _require_run(run_id)
    client_id(request)  # Require the run's authenticated researcher context.
    if not consent:
        raise HTTPException(
            status_code=422, detail="consent is required to index a document"
        )
    data = await file.read(document_ingest.MAX_UPLOAD_BYTES + 1)
    try:
        extracted = document_ingest.extract_document(
            data, file.content_type or "application/octet-stream"
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    title = (file.filename or "Uploaded document").strip()
    evidence_id = store.add_evidence(
        run_id,
        title,
        source=run_corpus.ATTACHMENT_SOURCE,
        abstract=extracted.text,
        mime_type=extracted.mime_type,
        sha256=extracted.sha256,
        byte_size=extracted.byte_size,
        document_version=extracted.sha256,
        extraction_tool=extracted.extraction_tool,
    )
    message = store.append_message(
        run_id,
        client_id(request),
        "Use the uploaded private research document "
        f"'{title}' in subsequent work.",
        "steering",
        meta={"kind": "attachment", "evidence_id": evidence_id},
    )
    continuation = engine_tasks.enqueue_scientist_continuation(
        run_id, message.id
    )
    store.append_event(
        run_id,
        "scientist.attachment",
        {"evidence_id": evidence_id, "title": title},
    )
    return {
        "id": evidence_id,
        "indexed": True,
        "sha256": extracted.sha256,
        "byte_size": extracted.byte_size,
        "mime_type": extracted.mime_type,
        "extraction_tool": extracted.extraction_tool,
        "continuation_task_id": continuation.id if continuation else None,
    }


@router.get("/{run_id}/attachments/search")
async def search_attachments(run_id: str, q: str) -> dict[str, Any]:
    """Retrieve a run's attachment corpus by keyword (Milestone 7).

    Proves the attachment path is a live retrieval corpus, not a dead
    connector: the scientist's uploaded documents are searchable via the
    run-scoped keyword retriever.
    """
    _require_run(run_id)
    documents = run_corpus.corpus_from_evidence(store.list_evidence(run_id))
    retriever = run_corpus.KeywordCorpusRetriever(documents)
    hits = retriever.retrieve(q)
    return {
        "results": [
            {
                "id": h.document.doc_id,
                "title": h.document.title,
                "score": h.score,
            }
            for h in hits
        ]
    }


@router.get("/{run_id}/report")
async def get_report(run_id: str) -> dict[str, Any]:
    """Return the latest structured report, or 404 before synthesis."""
    _require_run(run_id)
    report = store.get_latest_report(run_id)
    if not report:
        raise HTTPException(status_code=404, detail="no report yet")
    return report


@router.get("/{run_id}/report.md", response_class=PlainTextResponse)
async def get_report_markdown(run_id: str) -> PlainTextResponse:
    """Return the rendered Markdown report as a file download."""
    _require_run(run_id)
    md = store.read_report_markdown(run_id)
    if md is None:
        raise HTTPException(status_code=404, detail="no report yet")
    # Content-Disposition makes browsers save it as <run_id>.md.
    return PlainTextResponse(
        md,
        headers={
            "Content-Disposition": f'attachment; filename="{run_id}.md"',
        },
    )


# ---------------------------------------------------------------------------
# Chat / interaction endpoints
# ---------------------------------------------------------------------------


@router.post("/{run_id}/messages")
async def send_message(run_id: str, req: SendMessageRequest) -> dict[str, Any]:
    """Queue scientist steering and continue a completed engine run."""
    _require_run(run_id)
    # Stored with applied=0; the workflow drains pending steering messages
    # between iterations (store.get_pending_steering) and marks them applied.
    msg = store.append_message(run_id, "user", req.content, "steering")
    continuation = engine_tasks.enqueue_scientist_continuation(run_id, msg.id)
    return {
        **msg.to_dict(),
        "status": "queued",
        "continuation_task_id": continuation.id if continuation else None,
    }


@router.get("/{run_id}/messages")
async def list_messages(run_id: str) -> dict[str, Any]:
    """Return all messages for a run in chronological order."""
    _require_run(run_id)
    msgs = store.list_messages(run_id)
    return {"messages": [m.to_dict() for m in msgs]}


@router.post("/{run_id}/messages/ask")
async def ask_question(run_id: str, req: AskRequest) -> StreamingResponse:
    """Answer a question about the run using a fast LLM.

    The response is streamed back to the caller.
    """
    run = _run_or_404(run_id)

    # Persist the question first so history survives even if streaming fails.
    question_msg = store.append_message(run_id, "user", req.question, "qa")

    # All six reads target the same run; share one connection.
    with store.connect() as conn:
        hypotheses = store.list_hypotheses(run_id, conn=conn)
        reviews = store.list_reviews(run_id, conn=conn)
        matches = store.list_matches(run_id, conn=conn)
        # [:-1] drops the question just appended above from the history.
        history = store.list_messages(run_id, conn=conn)[:-1]
        evidence = store.list_evidence(run_id, conn=conn)
        citations = store.list_citations(run_id, conn=conn)

    # Prompt assembly and streaming are delegated to qa.py; the endpoint
    # only gathers state and wires the SSE response.
    manifest = qa.build_evidence_manifest(evidence, citations)

    # Keyless demo posture: with the mock provider selected there is no
    # language model to call, so synthesize a deterministic answer grounded in
    # the run's own artifacts rather than streaming an API-key error. The real
    # LLM path is unchanged for a configured provider.
    if engine_adapter.select_provider() == "mock":
        answer = qa.build_offline_answer(
            run.research_goal, hypotheses, reviews, manifest
        )
        return StreamingResponse(
            qa.stream_offline_answer(run_id, question_msg.id, answer, manifest),
            media_type="text/event-stream",
        )

    system_prompt = qa.build_system_prompt(
        run.research_goal, hypotheses, reviews, matches, history, manifest
    )
    return StreamingResponse(
        qa.stream_answer(
            run_id, req.question, question_msg.id, system_prompt, manifest
        ),
        media_type="text/event-stream",
    )
