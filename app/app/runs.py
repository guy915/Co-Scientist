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

The router maintains a per-run cancellation event in `_active`. Streams are
backed by the persisted event log so they survive client reconnects and full
backend restarts.
"""
# pylint: disable=inconsistent-quotes

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import engine_adapter, qa, store
from app.run_modes import (
    CANONICAL_RUN_MODE,
    RUN_FOCUS_PATTERN,
    RUN_TIER_PATTERN,
    normalize_run_focus,
    normalize_run_tier,
    resolved_run_config,
    setup_config,
)
from app.store import RunRow, RunStatus, TERMINAL_STATUSES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs", tags=["runs"])

# ---------------------------------------------------------------------------
# Active run registry (cancellation + new-event signalling per process)
# ---------------------------------------------------------------------------


class _RunHandle:
    """Per-run handle tracking cancellation and new-event signalling."""

    def __init__(self) -> None:
        # Set by /cancel; the workflow checks it between steps and stops.
        self.cancelled = asyncio.Event()
        # Pulsed by the runner after each workflow event so in-process SSE
        # streams can wake immediately instead of waiting out a poll tick.
        self.new_event = asyncio.Event()


# In-memory registry of workflows running in THIS process. Presence of a
# run_id doubles as the "already active" guard in start_run; entries are
# removed in the runner's finally block. After a restart the map is empty,
# which is why reconcile_interrupted_runs exists on the store side.
_active: dict[str, _RunHandle] = {}
_active_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateRunRequest(BaseModel):
    """Body for POST /api/runs; everything but the goal is optional."""

    research_goal: str = Field(..., min_length=1)
    # Free-form planning guidance lists; defaults are filled by setup_config
    # when omitted (direct API calls, seeded demos).
    requirements: list[str] | None = None
    attributes: list[str] | None = None
    criteria: list[str] | None = None
    # Regex-validated enums; invalid values are rejected with a 422 here,
    # while None falls through to normalize_run_* defaults.
    focus: str | None = Field(None, pattern=RUN_FOCUS_PATTERN)
    tier: str | None = Field(None, pattern=RUN_TIER_PATTERN)
    # Numeric knobs override the tier defaults (see resolved_run_config).
    initial_hypotheses_count: int | None = None
    max_iterations: int | None = None
    evolution_max_count: int | None = None
    k_factor: int | None = None
    enable_literature_review: bool | None = None


class StartRunRequest(BaseModel):
    """Body for POST /api/runs/{id}/start; optional provider override."""

    force_provider: str | None = Field(None, pattern="^(mock|engine)$")


class SendMessageRequest(BaseModel):
    """Body for POST /api/runs/{id}/messages (steering)."""

    content: str = Field(..., min_length=1)


class AskRequest(BaseModel):
    """Body for POST /api/runs/{id}/messages/ask (Q&A)."""

    question: str = Field(..., min_length=1)


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
    focus = normalize_run_focus(req.focus)
    tier = normalize_run_tier(req.tier)
    # `setup` is the durable planning block persisted inside config_json.
    setup = setup_config(
        research_goal=req.research_goal,
        requirements=req.requirements,
        attributes=req.attributes,
        criteria=req.criteria,
        focus=focus,
        tier=tier,
    )
    overrides: dict[str, Any] = {
        "tier": tier,
        "focus": focus,
        "setup": setup,
    }
    # Only explicitly-sent numeric knobs become overrides; absent fields
    # keep the tier defaults applied by resolved_run_config.
    if req.initial_hypotheses_count is not None:
        overrides["initial_hypotheses_count"] = req.initial_hypotheses_count
    if req.max_iterations is not None:
        overrides["max_iterations"] = req.max_iterations
    if req.evolution_max_count is not None:
        overrides["evolution_max_count"] = req.evolution_max_count
    if req.k_factor is not None:
        overrides["k_factor"] = req.k_factor
    if req.enable_literature_review is not None:
        overrides["enable_literature_review"] = req.enable_literature_review
    config = resolved_run_config(overrides)
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


@router.post("/{run_id}/start")
async def start_run(run_id: str, req: StartRunRequest,
                    background: BackgroundTasks) -> dict[str, Any]:
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
    # Status guards: only draft/failed/blocked/cancelled runs may (re)start.
    # In-progress and completed runs 409 rather than double-running.
    if run.status in (RunStatus.RUNNING, RunStatus.SYNTHESIZING):
        raise HTTPException(status_code=409, detail="run already in progress")
    if run.status == RunStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="run already completed")

    # Reserve the run atomically under the lock so two concurrent /start
    # requests cannot both pass the DB status check and launch twice.
    async with _active_lock:
        if run_id in _active:
            raise HTTPException(status_code=409, detail="run already active")
        handle = _RunHandle()
        _active[run_id] = handle

    # Transition draft -> queued before returning; the runner moves the run
    # to running/synthesizing/terminal states as the workflow progresses.
    store.update_run_status(run_id, RunStatus.QUEUED)
    store.append_event(run_id, "lifecycle", {"event": "queued"})

    async def runner() -> None:
        """Drive the workflow to completion as a background task."""
        try:
            # The adapter persists each event itself; this loop only pulses
            # new_event so any in-process SSE stream wakes immediately.
            async for _ in engine_adapter.run_workflow(
                    run_id=run_id,
                    research_goal=run.research_goal,
                    config=run.config,
                    cancelled=handle.cancelled,
                    force_provider=req.force_provider,
            ):
                handle.new_event.set()
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Catch-all so an unexpected workflow crash still lands the run
            # in a terminal FAILED state with a status event for the UI.
            logger.exception("workflow failed: %s", e)
            store.update_run_status(run_id, RunStatus.FAILED, error=str(e))
            store.append_event(run_id, "status", {
                "status": "failed",
                "error": str(e)
            })
            handle.new_event.set()
        finally:
            # Always release the active-run slot so the run can be restarted.
            async with _active_lock:
                _active.pop(run_id, None)

    # Returns immediately; FastAPI runs `runner` after the response is sent.
    background.add_task(runner)
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

    async def event_gen() -> AsyncGenerator[str, None]:
        """Yield SSE frames: full replay from `after`, then a live tail."""
        last_seq = after

        # Replay historical events first.
        # Clients reconnect with ?after= set to their last seen seq, so
        # replay is idempotent and gap-free.
        history = store.list_events(run_id, after_seq=last_seq)
        for ev in history:
            last_seq = ev["seq"]
            yield qa.sse_frame(ev)

        # If terminal already, send a final marker and return.
        # `_terminal` is a synthetic frame (never persisted) telling
        # clients to close.
        terminal = run.status in TERMINAL_STATUSES
        if terminal:
            yield qa.sse_frame({
                "type": "_terminal",
                "payload": {
                    "status": run.status
                },
                "seq": last_seq
            })
            return

        # Handle is present only when this process runs the workflow; other
        # processes (or post-restart streams) fall back to pure polling.
        async with _active_lock:
            handle = _active.get(run_id)

        # Live tail. Poll the store; the in-process handle's `new_event` cuts
        # latency when we are the producing process. Cap with a wall-clock
        # so a stale connection doesn't hang forever.
        for tick in range(10_000):  # 10k * 0.5s = ~83 minutes max stream
            if await request.is_disconnected():
                return

            signaled = True
            if handle is not None:
                # Wake early on the producer's pulse; clear before querying
                # so a set that races the query is caught next iteration.
                try:
                    await asyncio.wait_for(handle.new_event.wait(), timeout=0.5)
                    handle.new_event.clear()
                except asyncio.TimeoutError:
                    signaled = False
            else:
                # No in-process producer: plain fixed-interval polling.
                await asyncio.sleep(0.5)

            # With an in-process producer, every appended event sets
            # `new_event`.
            # A timed-out wait therefore means nothing was written, so skip the
            # query -- except on the every-10th-tick terminal-status safety net.
            if handle is not None and not signaled and tick % 10 != 9:
                continue

            new_events = store.list_events(run_id, after_seq=last_seq)
            terminal_status: str | None = None
            for ev in new_events:
                last_seq = ev["seq"]
                yield qa.sse_frame(ev)
                if ev["type"] == "status":
                    status = (ev.get("payload") or {}).get("status")
                    if status in TERMINAL_STATUSES:
                        terminal_status = status

            # Exit on terminal. A terminal transition normally rides on a new
            # event (all workflow paths append a `status` event), so ticks
            # without one skip the run-row query; the every-10th tick check
            # covers terminal writes that append no event.
            if terminal_status is None and tick % 10 == 9:
                current = store.get_run(run_id)
                if current and current.status in TERMINAL_STATUSES:
                    terminal_status = current.status
            if terminal_status is not None:
                yield qa.sse_frame({
                    "type": "_terminal",
                    "payload": {
                        "status": terminal_status
                    },
                    "seq": last_seq
                })
                return

    return StreamingResponse(
        event_gen(),
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
    """Answer a question about the run using a fast LLM, streaming the response."""  # pylint: disable=line-too-long
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
    system_prompt = qa.build_system_prompt(run.research_goal, hypotheses,
                                           reviews, matches, history, manifest)
    return StreamingResponse(
        qa.stream_answer(run_id, req.question, question_msg.id, system_prompt,
                         manifest),
        media_type="text/event-stream",
    )
