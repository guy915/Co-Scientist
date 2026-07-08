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
import json
import logging
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
        self.cancelled = asyncio.Event()
        self.new_event = asyncio.Event()


_active: dict[str, _RunHandle] = {}
_active_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateRunRequest(BaseModel):
    research_goal: str = Field(..., min_length=1)
    requirements: list[str] | None = None
    attributes: list[str] | None = None
    criteria: list[str] | None = None
    focus: str | None = Field(None, pattern=RUN_FOCUS_PATTERN)
    tier: str | None = Field(None, pattern=RUN_TIER_PATTERN)
    initial_hypotheses_count: int | None = None
    max_iterations: int | None = None
    evolution_max_count: int | None = None
    k_factor: int | None = None
    enable_literature_review: bool | None = None


class StartRunRequest(BaseModel):
    force_provider: str | None = Field(None, pattern="^(mock|engine)$")


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_or_404(run_id: str) -> RunRow:
    run = store.get_run(run_id)
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


def _client_id(request: Request) -> str:
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
    provider = engine_adapter.select_provider()
    run_mode = CANONICAL_RUN_MODE
    focus = normalize_run_focus(req.focus)
    tier = normalize_run_tier(req.tier)
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
    run = store.create_run(
        research_goal=req.research_goal,
        profile=run_mode,
        provider=provider,
        config=config,
        client_id=_client_id(request),
    )
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
    runs = store.list_runs(client_id=_client_id(request), limit=limit)
    return {"runs": [r.to_dict() for r in runs]}


@router.get("/demo")
async def list_demo_runs() -> dict[str, Any]:
    runs = store.list_runs(client_id=store.DEMO_CLIENT_ID)
    return {"runs": [r.to_dict() for r in runs]}


@router.get("/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    run = _run_or_404(run_id)
    return {**run.to_dict(), "summary": store.summary_counts(run_id)}


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
    if run.status in (RunStatus.RUNNING, RunStatus.SYNTHESIZING):
        raise HTTPException(status_code=409, detail="run already in progress")
    if run.status == RunStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="run already completed")

    async with _active_lock:
        if run_id in _active:
            raise HTTPException(status_code=409, detail="run already active")
        handle = _RunHandle()
        _active[run_id] = handle

    store.update_run_status(run_id, RunStatus.QUEUED)
    store.append_event(run_id, "lifecycle", {"event": "queued"})

    async def runner() -> None:
        try:
            async for _ in engine_adapter.run_workflow(
                    run_id=run_id,
                    research_goal=run.research_goal,
                    config=run.config,
                    cancelled=handle.cancelled,
                    force_provider=req.force_provider,
            ):
                handle.new_event.set()
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception("workflow failed: %s", e)
            store.update_run_status(run_id, RunStatus.FAILED, error=str(e))
            store.append_event(run_id, "status", {
                "status": "failed",
                "error": str(e)
            })
            handle.new_event.set()
        finally:
            async with _active_lock:
                _active.pop(run_id, None)

    background.add_task(runner)
    return {"id": run_id, "status": "queued"}


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    _require_run(run_id)
    async with _active_lock:
        handle = _active.get(run_id)
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
        last_seq = after

        # Replay historical events first.
        history = store.list_events(run_id, after_seq=last_seq)
        for ev in history:
            last_seq = ev["seq"]
            yield _sse(ev)

        # If terminal already, send a final marker and return.
        terminal = run.status in TERMINAL_STATUSES
        if terminal:
            yield _sse({
                "type": "_terminal",
                "payload": {
                    "status": run.status
                },
                "seq": last_seq
            })
            return

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
                try:
                    await asyncio.wait_for(handle.new_event.wait(), timeout=0.5)
                    handle.new_event.clear()
                except asyncio.TimeoutError:
                    signaled = False
            else:
                await asyncio.sleep(0.5)

            # With an in-process producer, every appended event sets `new_event`.
            # A timed-out wait therefore means nothing was written, so skip the
            # query -- except on the every-10th-tick terminal-status safety net.
            if handle is not None and not signaled and tick % 10 != 9:
                continue

            new_events = store.list_events(run_id, after_seq=last_seq)
            terminal_status: str | None = None
            for ev in new_events:
                last_seq = ev["seq"]
                yield _sse(ev)
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
                yield _sse({
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
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@router.get("/{run_id}/hypotheses")
async def get_hypotheses(run_id: str) -> dict[str, Any]:
    _require_run(run_id)
    return {"hypotheses": store.list_hypotheses(run_id)}


@router.get("/{run_id}/evidence")
async def get_evidence(run_id: str) -> dict[str, Any]:
    _require_run(run_id)
    return {"evidence": store.list_evidence(run_id)}


@router.get("/{run_id}/matches")
async def get_matches(run_id: str) -> dict[str, Any]:
    _require_run(run_id)
    return {"matches": store.list_matches(run_id)}


@router.get("/{run_id}/reviews")
async def get_reviews(run_id: str) -> dict[str, Any]:
    _require_run(run_id)
    return {"reviews": store.list_reviews(run_id)}


@router.get("/{run_id}/safety")
async def get_safety(run_id: str) -> dict[str, Any]:
    _require_run(run_id)
    return {"safety": store.list_safety_decisions(run_id)}


@router.get("/{run_id}/citations")
async def get_citations(run_id: str) -> dict[str, Any]:
    _require_run(run_id)
    return {"citations": store.list_citations(run_id)}


@router.get("/{run_id}/report")
async def get_report(run_id: str) -> dict[str, Any]:
    _require_run(run_id)
    report = store.get_latest_report(run_id)
    if not report:
        raise HTTPException(status_code=404, detail="no report yet")
    return report


@router.get("/{run_id}/report.md", response_class=PlainTextResponse)
async def get_report_markdown(run_id: str) -> PlainTextResponse:
    _require_run(run_id)
    md = store.read_report_markdown(run_id)
    if md is None:
        raise HTTPException(status_code=404, detail="no report yet")
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

    question_msg = store.append_message(run_id, "user", req.question, "qa")

    # All six reads target the same run; share one connection.
    with store.connect() as conn:
        hypotheses = store.list_hypotheses(run_id, conn=conn)
        reviews = store.list_reviews(run_id, conn=conn)
        matches = store.list_matches(run_id, conn=conn)
        history = store.list_messages(run_id, conn=conn)[:-1]
        evidence = store.list_evidence(run_id, conn=conn)
        citations = store.list_citations(run_id, conn=conn)

    manifest = qa.build_evidence_manifest(evidence, citations)
    system_prompt = qa.build_system_prompt(run.research_goal, hypotheses,
                                           reviews, matches, history, manifest)
    return StreamingResponse(
        qa.stream_answer(run_id, req.question, question_msg.id, system_prompt,
                         manifest),
        media_type="text/event-stream",
    )
