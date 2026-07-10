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
- GET    /api/runs/{id}/report            structured report payload (latest)
- GET    /api/runs/{id}/report.md         rendered Markdown report

The router maintains a per-run cancellation event in `_active` (defined in
``runs_registry``). Streams are backed by the persisted event log so they
survive client reconnects and full backend restarts. Request models and SSE
streaming helpers live in ``runs_models`` and ``runs_events`` respectively, and
are re-exported here so the ``app.runs.<name>`` import paths stay stable.
"""
# pylint: disable=inconsistent-quotes

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse

from app import engine_adapter, qa, store
from app.run_modes import CANONICAL_RUN_MODE
from app.runs_events import _drain_tick_frames as _drain_tick_frames
from app.runs_events import _event_stream as _event_stream
from app.runs_events import _resolve_tick_terminal as _resolve_tick_terminal
from app.runs_events import _should_skip_tick as _should_skip_tick
from app.runs_events import _stream_live_tail as _stream_live_tail
from app.runs_events import _terminal_frame as _terminal_frame
from app.runs_events import (
    _terminal_status_from_event as _terminal_status_from_event,
)
from app.runs_events import (
    _terminal_status_from_run as _terminal_status_from_run,
)
from app.runs_models import AskRequest as AskRequest
from app.runs_models import CreateRunRequest as CreateRunRequest
from app.runs_models import SendMessageRequest as SendMessageRequest
from app.runs_models import StartRunRequest as StartRunRequest
from app.runs_models import _build_create_run_config as _build_create_run_config
from app.runs_models import (
    _run_overrides_from_request as _run_overrides_from_request,
)
from app.runs_registry import _active as _active
from app.runs_registry import _active_lock as _active_lock
from app.runs_registry import _RunHandle as _RunHandle
from app.store import RunRow, RunStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs", tags=["runs"])

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


# Client isolation is header-based: the frontend sends a per-browser
# X-Client-ID and list endpoints only return runs created with the same id.
# A missing header yields '' (shared by all header-less callers). This is
# scoping for a friendlier multi-user demo, not authentication.
def _client_id(request: Request) -> str:
    """Return the caller's client id from the X-Client-ID header."""
    return request.headers.get("X-Client-ID", "")


@router.post("")
async def create_run(req: CreateRunRequest, request: Request) -> dict[str, Any]:
    """Create a new run for the requesting client and return it.

    Args:
        req: Request body with the research goal, run mode, and run config.
        request: Incoming HTTP request, used to read the client identifier.

    Returns:
        The created run serialized as a dict.
    """
    # Provider (engine vs mock) is decided at creation from availability;
    # /start can still override it per run via force_provider.
    provider = engine_adapter.select_provider()
    run_mode = CANONICAL_RUN_MODE
    config, focus, tier = _build_create_run_config(req)
    # The run is persisted in DRAFT; nothing executes until /start is called.
    run = store.create_run(
        research_goal=req.research_goal,
        profile=run_mode,
        provider=provider,
        config=config,
        client_id=_client_id(request),
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
    return run.to_dict()


@router.get("")
async def list_runs(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    """List the requesting client's runs, most recent first."""
    runs = store.list_runs(client_id=_client_id(request), limit=limit)
    return {"runs": [r.to_dict() for r in runs]}


# Registered before /{run_id} so the literal path wins route matching.
@router.get("/demo")
async def list_demo_runs() -> dict[str, Any]:
    """List the seeded demo runs, which are visible to every client."""
    runs = store.list_runs(client_id=store.DEMO_CLIENT_ID)
    return {"runs": [r.to_dict() for r in runs]}


@router.get("/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    """Return a run's details plus per-table summary counts."""
    # One connection shared across the run lookup and its summary counts.
    with store.connect() as conn:
        run = _run_or_404(run_id, conn=conn)
        summary = store.summary_counts(run_id, conn=conn)
    return {**run.to_dict(), "summary": summary}


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
) -> None:
    """Drive a run's workflow to completion as a background task.

    Args:
        run_id: Identifier of the run to drive.
        research_goal: The run's research goal, passed through to the engine.
        config: The run's resolved configuration.
        force_provider: Optional provider override ('mock' or 'engine').
        handle: The run's registry handle for cancellation/new-event signals.
    """
    try:
        # The adapter persists each event itself; this loop only pulses
        # new_event so any in-process SSE stream wakes immediately.
        async for _ in engine_adapter.run_workflow(
            run_id=run_id,
            research_goal=research_goal,
            config=config,
            cancelled=handle.cancelled,
            force_provider=force_provider,
        ):
            handle.new_event.set()
    except Exception as e:  # pylint: disable=broad-exception-caught
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
    if run.status in (RunStatus.RUNNING, RunStatus.SYNTHESIZING):
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
    handle = await _reserve_active_slot(run_id)

    # Transition draft -> queued before returning; the runner moves the run
    # to running/synthesizing/terminal states as the workflow progresses.
    store.update_run_status(run_id, RunStatus.QUEUED)
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
    """Request cancellation of an actively running workflow.

    Cancellation is cooperative: this only sets the handle's event. The
    workflow notices at its next checkpoint and transitions the run to
    CANCELLED itself, so the response says 'cancelling', not 'cancelled'.
    """
    _require_run(run_id)
    async with _active_lock:
        handle = _active.get(run_id)
    # A run without an in-process handle is not running here (finished, or
    # the server restarted since it started), so there is nothing to cancel.
    if not handle:
        raise HTTPException(status_code=404, detail="run is not active")
    handle.cancelled.set()
    store.append_event(run_id, "lifecycle", {"event": "cancel_requested"})
    return {"id": run_id, "status": "cancelling"}


# ---------------------------------------------------------------------------
# SSE events
# ---------------------------------------------------------------------------


@router.get("/{run_id}/events")
async def stream_events(
    run_id: str,
    request: Request,
    after: int = Query(0, ge=0),
) -> StreamingResponse:
    """Stream a run's events as Server-Sent Events.

    Args:
        run_id: Path identifier of the run to stream.
        request: Incoming HTTP request, used to detect client disconnects.
        after: Only stream events with a sequence number greater than this.

    Returns:
        A StreamingResponse that replays history then tails live events.
    """
    run = _run_or_404(run_id)
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
    """Return the run's hypotheses with Elo state and lineage fields."""
    _require_run(run_id)
    return {"hypotheses": store.list_hypotheses(run_id)}


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


@router.get("/{run_id}/citations")
async def get_citations(run_id: str) -> dict[str, Any]:
    """Return the run's citation rows with classification states."""
    _require_run(run_id)
    return {"citations": store.list_citations(run_id)}


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
    """Queue a user steering message for the next iteration."""
    _require_run(run_id)
    # Stored with applied=0; the workflow drains pending steering messages
    # between iterations (store.get_pending_steering) and marks them applied.
    msg = store.append_message(run_id, "user", req.content, "steering")
    return {**msg.to_dict(), "status": "queued"}


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
    system_prompt = qa.build_system_prompt(
        run.research_goal, hypotheses, reviews, matches, history, manifest
    )
    return StreamingResponse(
        qa.stream_answer(
            run_id, req.question, question_msg.id, system_prompt, manifest
        ),
        media_type="text/event-stream",
    )
