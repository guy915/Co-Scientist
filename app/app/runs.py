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
import os
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import engine_adapter, store
from app.run_modes import (
    RUN_FOCUS_PATTERN,
    RUN_MODE_PATTERN,
    RUN_TIER_PATTERN,
    normalize_run_focus,
    normalize_run_mode,
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


def _db_path() -> str | None:
    return os.getenv("COSCIENTIST_DB_PATH") or None


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateRunRequest(BaseModel):
    research_goal: str = Field(..., min_length=1)
    run_mode: str | None = Field(None, pattern=RUN_MODE_PATTERN)
    profile: str | None = Field(None, pattern=RUN_MODE_PATTERN)
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
    notes: str | None = None


class StartRunRequest(BaseModel):
    force_provider: str | None = Field(None, pattern="^(mock|engine)$")


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)


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


def _run_or_404(run_id: str) -> RunRow:
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
    """Create a new run for the requesting client and return it.

    Args:
        req: Request body with the research goal, run mode, and run config.
        request: Incoming HTTP request, used to read the client identifier.

    Returns:
        The created run serialized as a dict.
    """
    provider = engine_adapter.select_provider()
    run_mode = normalize_run_mode(req.run_mode or req.profile)
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
    config = resolved_run_config(run_mode, overrides)
    run = store.create_run(
        research_goal=req.research_goal,
        profile=run_mode,
        provider=provider,
        config=config,
        client_id=_client_id(request),
        db_path=_db_path(),
    )
    store.append_event(
        run.id,
        "lifecycle",
        {
            "event": "created",
            "run_mode": run_mode,
            "profile": run_mode,
            "provider": provider,
            "focus": focus,
            "tier": tier,
        },
        db_path=_db_path(),
    )
    return run.to_dict()


@router.get("")
async def list_runs(
        request: Request,
        limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    runs = store.list_runs(client_id=_client_id(request),
                           limit=limit,
                           db_path=_db_path())
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

    store.update_run_status(run_id, RunStatus.QUEUED, db_path=_db_path())
    store.append_event(run_id,
                       "lifecycle", {"event": "queued"},
                       db_path=_db_path())

    async def runner() -> None:
        try:
            async for _ in engine_adapter.run_workflow(
                    run_id=run_id,
                    research_goal=run.research_goal,
                    profile=normalize_run_mode(run.profile),
                    config=run.config,
                    db_path=_db_path(),
                    cancelled=handle.cancelled,
                    force_provider=req.force_provider,
            ):
                handle.new_event.set()
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception("workflow failed: %s", e)
            store.update_run_status(run_id,
                                    RunStatus.FAILED,
                                    error=str(e),
                                    db_path=_db_path())
            store.append_event(run_id,
                               "status", {
                                   "status": "failed",
                                   "error": str(e)
                               },
                               db_path=_db_path())
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
    store.append_event(run_id,
                       "lifecycle", {"event": "cancel_requested"},
                       db_path=_db_path())
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
        history = store.list_events(run_id,
                                    after_seq=last_seq,
                                    db_path=_db_path())
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

            new_events = store.list_events(run_id,
                                           after_seq=last_seq,
                                           db_path=_db_path())
            for ev in new_events:
                last_seq = ev["seq"]
                yield _sse(ev)

            # Re-check run status; exit on terminal.
            current = store.get_run(run_id, db_path=_db_path())
            if current and current.status in TERMINAL_STATUSES:
                yield _sse({
                    "type": "_terminal",
                    "payload": {
                        "status": current.status
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


# ---------------------------------------------------------------------------
# Chat / interaction endpoints
# ---------------------------------------------------------------------------


@router.post("/{run_id}/messages")
async def send_message(run_id: str, req: SendMessageRequest) -> dict[str, Any]:
    """Queue a user steering message for the next iteration."""
    _run_or_404(run_id)
    msg = store.append_message(run_id,
                               "user",
                               req.content,
                               "steering",
                               db_path=_db_path())
    return {**msg.to_dict(), "status": "queued"}


@router.get("/{run_id}/messages")
async def list_messages(run_id: str) -> dict[str, Any]:
    """Return all messages for a run in chronological order."""
    _run_or_404(run_id)
    msgs = store.list_messages(run_id, db_path=_db_path())
    return {"messages": [m.to_dict() for m in msgs]}


_CITATION_STATE_RANK = {
    "verified": 3,
    "partial": 2,
    "unsupported": 1,
    "unavailable": 0,
}


def _build_evidence_manifest(
    evidence: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    cap: int = 12,
) -> list[dict[str, Any]]:
    """Build a numbered, deterministic source list for grounded Q&A.

    Cited evidence comes first (in citation order, keeping the strongest state
    when an item is cited by several claims), then any remaining evidence, all
    capped to keep the prompt bounded. Each entry carries the fields the model
    needs to cite and the UI needs to render a reference chip.

    Args:
        evidence: Evidence rows for the run.
        citations: Citation rows for the run.
        cap: Maximum number of sources to include.

    Returns:
        A list of ``{n, evidence_id, title, url, source, year, state}`` dicts.
    """
    by_id: dict[str, dict[str, Any]] = {
        str(e["id"]): e for e in evidence if e.get("id") is not None
    }
    cited_state: dict[str, str] = {}
    cited_order: list[str] = []
    for citation in citations:
        raw_eid = citation.get("evidence_id")
        if raw_eid is None:
            continue
        eid = str(raw_eid)
        if eid not in by_id:
            continue
        state = str(citation.get("state") or "")
        if eid not in cited_state:
            cited_order.append(eid)
            cited_state[eid] = state
        elif _CITATION_STATE_RANK.get(state, -1) > _CITATION_STATE_RANK.get(
                cited_state[eid], -1):
            cited_state[eid] = state
    ordered_ids = cited_order + [eid for eid in by_id if eid not in cited_state]
    manifest: list[dict[str, Any]] = []
    for n, eid in enumerate(ordered_ids[:cap], start=1):
        row = by_id[eid]
        entry_state = cited_state.get(eid)
        if entry_state is None:
            entry_state = ("available"
                           if row.get("available", True) else "unavailable")
        manifest.append({
            "n": n,
            "evidence_id": eid,
            "title": row.get("title") or "Untitled source",
            "url": row.get("url"),
            "source": row.get("source"),
            "year": row.get("year"),
            "state": entry_state,
        })
    return manifest


def _format_manifest_for_prompt(manifest: list[dict[str, Any]]) -> str:
    """Render the manifest as numbered lines for the system prompt."""
    lines = []
    for entry in manifest:
        meta = ", ".join(
            str(part)
            for part in (entry.get("source"), entry.get("year"))
            if part)
        suffix = f" ({meta})" if meta else ""
        lines.append(f"[{entry['n']}] {entry['title']}{suffix}"
                     f" — {entry['state']}")
    return "\n".join(lines)


@router.post("/{run_id}/messages/ask")
async def ask_question(run_id: str, req: AskRequest) -> StreamingResponse:
    """Answer a question about the run using a fast LLM, streaming the response."""  # pylint: disable=line-too-long
    run = _run_or_404(run_id)

    question_msg = store.append_message(run_id,
                                        "user",
                                        req.question,
                                        "qa",
                                        db_path=_db_path())

    hypotheses = store.list_hypotheses(run_id, db_path=_db_path())
    reviews = store.list_reviews(run_id, db_path=_db_path())
    matches = store.list_matches(run_id, db_path=_db_path())
    history = store.list_messages(run_id, db_path=_db_path())[:-1]
    evidence = store.list_evidence(run_id, db_path=_db_path())
    citations = store.list_citations(run_id, db_path=_db_path())
    manifest = _build_evidence_manifest(evidence, citations)
    evidence_lines = _format_manifest_for_prompt(manifest)

    top_hyps = sorted(hypotheses,
                      key=lambda h: -int(h.get("elo_rating") or 1200))[:5]
    hyp_lines = "\n".join(
        f"- [{h['title']}] Elo {h.get('elo_rating', 1200)}, {h.get('win_count', 0)}W/{h.get('loss_count', 0)}L"  # pylint: disable=line-too-long
        for h in top_hyps)
    review_lines = "\n".join(
        f"- {r['reviewer_agent']} on {r['hypothesis_id'][:8]}: {r['summary'][:120]}"  # pylint: disable=line-too-long
        for r in reviews[-5:])
    match_lines = "\n".join(
        f"- Winner {m['winner_id'][:8]} (Elo {m['winner_elo_after']}) — {(m.get('rationale') or '')[:100]}"  # pylint: disable=line-too-long
        for m in matches[-3:])
    conv_lines = "\n".join(
        f"{'User' if m.sender == 'user' else 'Assistant'}: {m.content}"
        for m in history[-10:])

    system_prompt = (
        f"You are a concise research assistant helping the user understand an ongoing "  # pylint: disable=line-too-long
        f"AI-driven hypothesis generation run.\n\n"
        f"Research goal: {run.research_goal}\n\n"
        f"Top hypotheses by Elo:\n{hyp_lines or '(none yet)'}\n\n"
        f"Recent reviews:\n{review_lines or '(none yet)'}\n\n"
        f"Recent tournament matches:\n{match_lines or '(none yet)'}\n\n"
        f"Evidence (cite supporting sources inline as [n] using ONLY this "
        f"numbered list; never invent a citation):\n"
        f"{evidence_lines or '(no evidence retrieved)'}\n\n"
        f"Conversation history:\n{conv_lines or '(none)'}\n\n"
        f"Answer concisely and accurately. Do not repeat the question. When a "
        f"statement is supported by a listed source, cite it inline as [n].")

    model = os.getenv("CHAT_MODEL_NAME") or os.getenv("MODEL_NAME",
                                                      "deepseek/deepseek-chat")

    async def _stream() -> AsyncGenerator[str, None]:
        try:
            import litellm  # pylint: disable=import-outside-toplevel

            # Send the cited-source manifest first so the UI can resolve [n]
            # references as the answer streams in.
            if manifest:
                yield f"data: {json.dumps({'type': 'sources', 'sources': manifest})}\n\n"  # pylint: disable=line-too-long

            full: list[str] = []
            response = await litellm.acompletion(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": req.question
                    },
                ],
                stream=True,
            )
            async for chunk in response:
                delta = (chunk.choices[0].delta.content or
                         "") if chunk.choices else ""
                if delta:
                    full.append(delta)
                    yield f"data: {json.dumps({'type': 'chunk', 'content': delta})}\n\n"  # pylint: disable=line-too-long

            answer = "".join(full)
            store.append_message(
                run_id,
                "system",
                answer,
                "qa",
                db_path=_db_path(),
                meta={"sources": manifest} if manifest else None)
            yield f"data: {json.dumps({'type': 'done', 'question_id': question_msg.id})}\n\n"  # pylint: disable=line-too-long
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Q&A stream error for run %s: %s", run_id, exc)
            fallback = "Q&A requires a language model API key (set CHAT_MODEL_NAME or MODEL_NAME)."  # pylint: disable=line-too-long
            store.append_message(run_id,
                                 "system",
                                 fallback,
                                 "qa",
                                 db_path=_db_path())
            yield f"data: {json.dumps({'type': 'error', 'message': fallback})}\n\n"  # pylint: disable=line-too-long

    return StreamingResponse(_stream(), media_type="text/event-stream")
