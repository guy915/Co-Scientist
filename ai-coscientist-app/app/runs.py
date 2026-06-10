"""Run lifecycle router.

Endpoints:
- POST   /api/runs                        create a draft run
- GET    /api/runs                        list runs (most recent first)
- GET    /api/runs/{id}                   read run + summary counts
- POST   /api/runs/{id}/start             start the workflow (background)
- POST   /api/runs/{id}/cancel            cancel a running workflow
- GET    /api/runs/{id}/events            SSE stream (live + replay from `?after=`)
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

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import engine_adapter, store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs", tags=["runs"])


# ---------------------------------------------------------------------------
# Active run registry (cancellation + new-event signalling per process)
# ---------------------------------------------------------------------------


class _RunHandle:
    def __init__(self) -> None:
        self.cancelled = asyncio.Event()
        self.new_event = asyncio.Event()


_active: dict[str, _RunHandle] = {}
_active_lock = asyncio.Lock()


def _db_path() -> str | None:
    return os.getenv("COSCIENTIST_DB_PATH") or None


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateRunRequest(BaseModel):
    research_goal: str = Field(..., min_length=1)
    profile: str = Field("standard", pattern="^(standard|advanced)$")
    initial_hypotheses_count: int | None = None
    max_iterations: int | None = None
    evolution_max_count: int | None = None
    k_factor: int | None = None
    notes: str | None = None


class StartRunRequest(BaseModel):
    force_provider: str | None = Field(None, pattern="^(mock|engine)$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summary_counts(run_id: str) -> dict[str, int]:
    return {
        "events": len(store.list_events(run_id, db_path=_db_path())),
        "hypotheses": len(store.list_hypotheses(run_id, db_path=_db_path())),
        "evidence": len(store.list_evidence(run_id, db_path=_db_path())),
        "matches": len(store.list_matches(run_id, db_path=_db_path())),
        "reviews": len(store.list_reviews(run_id, db_path=_db_path())),
    }


def _run_or_404(run_id: str):
    run = store.get_run(run_id, db_path=_db_path())
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def _client_id(request: Request) -> str:
    return request.headers.get("X-Client-ID", "")


@router.post("")
async def create_run(req: CreateRunRequest, request: Request) -> dict[str, Any]:
    provider = engine_adapter.select_provider()
    config = {
        "initial_hypotheses_count": req.initial_hypotheses_count,
        "max_iterations": req.max_iterations,
        "evolution_max_count": req.evolution_max_count,
        "k_factor": req.k_factor,
        "notes": req.notes,
    }
    run = store.create_run(
        research_goal=req.research_goal,
        profile=req.profile,
        provider=provider,
        config={k: v for k, v in config.items() if v is not None},
        client_id=_client_id(request),
        db_path=_db_path(),
    )
    store.append_event(
        run.id,
        "lifecycle",
        {"event": "created", "profile": req.profile, "provider": provider},
        db_path=_db_path(),
    )
    return run.to_dict()


@router.get("")
async def list_runs(request: Request) -> dict[str, Any]:
    runs = store.list_runs(client_id=_client_id(request), db_path=_db_path())
    return {"runs": [r.to_dict() for r in runs]}


@router.get("/demo")
async def list_demo_runs() -> dict[str, Any]:
    runs = store.list_runs(client_id="__demo__", db_path=_db_path())
    return {"runs": [r.to_dict() for r in runs]}


@router.get("/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    run = _run_or_404(run_id)
    return {**run.to_dict(), "summary": _summary_counts(run_id)}


@router.post("/{run_id}/start")
async def start_run(
    run_id: str, req: StartRunRequest, background: BackgroundTasks
) -> dict[str, Any]:
    run = _run_or_404(run_id)
    if run.status in ("running", "synthesizing"):
        raise HTTPException(status_code=409, detail="run already in progress")
    if run.status == "completed":
        raise HTTPException(status_code=409, detail="run already completed")

    async with _active_lock:
        if run_id in _active:
            raise HTTPException(status_code=409, detail="run already active")
        handle = _RunHandle()
        _active[run_id] = handle

    store.update_run_status(run_id, "queued", db_path=_db_path())
    store.append_event(run_id, "lifecycle", {"event": "queued"}, db_path=_db_path())

    async def runner() -> None:
        try:
            async for _event in engine_adapter.run_workflow(
                run_id=run_id,
                research_goal=run.research_goal,
                profile=run.profile,
                config=run.config,
                db_path=_db_path(),
                cancelled=handle.cancelled,
                force_provider=req.force_provider,
            ):
                handle.new_event.set()
        except Exception as e:
            logger.exception("workflow failed: %s", e)
            store.update_run_status(run_id, "failed", error=str(e), db_path=_db_path())
            store.append_event(
                run_id, "status", {"status": "failed", "error": str(e)}, db_path=_db_path()
            )
            handle.new_event.set()
        finally:
            async with _active_lock:
                _active.pop(run_id, None)

    background.add_task(runner)
    return {"id": run_id, "status": "queued"}


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    _run_or_404(run_id)
    async with _active_lock:
        handle = _active.get(run_id)
    if not handle:
        raise HTTPException(status_code=404, detail="run is not active")
    handle.cancelled.set()
    store.append_event(run_id, "lifecycle", {"event": "cancel_requested"}, db_path=_db_path())
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
    run = _run_or_404(run_id)

    async def event_gen() -> AsyncGenerator[str, None]:
        last_seq = after

        # Replay historical events first.
        history = store.list_events(run_id, after_seq=last_seq, db_path=_db_path())
        for ev in history:
            last_seq = ev["seq"]
            yield _sse(ev)

        # If terminal already, send a final marker and return.
        terminal = run.status in ("completed", "failed", "cancelled", "blocked")
        if terminal:
            yield _sse({"type": "_terminal", "payload": {"status": run.status}, "seq": last_seq})
            return

        async with _active_lock:
            handle = _active.get(run_id)

        # Live tail. Poll the store; the in-process handle's `new_event` cuts
        # latency when we are the producing process. Cap with a wall-clock
        # so a stale connection doesn't hang forever.
        for _ in range(10_000):  # 10k * 0.5s = ~83 minutes max stream
            if await request.is_disconnected():
                return

            if handle is not None:
                try:
                    await asyncio.wait_for(handle.new_event.wait(), timeout=0.5)
                    handle.new_event.clear()
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(0.5)

            new_events = store.list_events(run_id, after_seq=last_seq, db_path=_db_path())
            for ev in new_events:
                last_seq = ev["seq"]
                yield _sse(ev)

            # Re-check run status; exit on terminal.
            current = store.get_run(run_id, db_path=_db_path())
            if current and current.status in ("completed", "failed", "cancelled", "blocked"):
                yield _sse(
                    {"type": "_terminal", "payload": {"status": current.status}, "seq": last_seq}
                )
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


@router.get("/{run_id}/events/log")
async def get_events_log(run_id: str) -> list[dict[str, Any]]:
    """Return all stored events for a run as JSON (for the log console)."""
    _run_or_404(run_id)
    return store.list_events(run_id, after_seq=0, db_path=_db_path())


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@router.get("/{run_id}/hypotheses")
async def get_hypotheses(run_id: str) -> dict[str, Any]:
    _run_or_404(run_id)
    return {"hypotheses": store.list_hypotheses(run_id, db_path=_db_path())}


@router.get("/{run_id}/evidence")
async def get_evidence(run_id: str) -> dict[str, Any]:
    _run_or_404(run_id)
    return {"evidence": store.list_evidence(run_id, db_path=_db_path())}


@router.get("/{run_id}/matches")
async def get_matches(run_id: str) -> dict[str, Any]:
    _run_or_404(run_id)
    return {"matches": store.list_matches(run_id, db_path=_db_path())}


@router.get("/{run_id}/reviews")
async def get_reviews(run_id: str) -> dict[str, Any]:
    _run_or_404(run_id)
    return {"reviews": store.list_reviews(run_id, db_path=_db_path())}


@router.get("/{run_id}/safety")
async def get_safety(run_id: str) -> dict[str, Any]:
    _run_or_404(run_id)
    return {"safety": store.list_safety_decisions(run_id, db_path=_db_path())}


@router.get("/{run_id}/citations")
async def get_citations(run_id: str) -> dict[str, Any]:
    _run_or_404(run_id)
    return {"citations": store.list_citations(run_id, db_path=_db_path())}


@router.get("/{run_id}/report")
async def get_report(run_id: str) -> dict[str, Any]:
    _run_or_404(run_id)
    report = store.get_latest_report(run_id, db_path=_db_path())
    if not report:
        raise HTTPException(status_code=404, detail="no report yet")
    return report


@router.get("/{run_id}/report.md", response_class=PlainTextResponse)
async def get_report_markdown(run_id: str) -> PlainTextResponse:
    _run_or_404(run_id)
    md = store.read_report_markdown(run_id, db_path=_db_path())
    if md is None:
        raise HTTPException(status_code=404, detail="no report yet")
    return PlainTextResponse(
        md,
        headers={
            "Content-Disposition": f'attachment; filename="{run_id}.md"',
        },
    )
