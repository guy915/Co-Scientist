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

Cancellation and pause are durable: they revoke the run's queued/leased
tasks and update the run row, which the workers observe. Streams are backed
by the persisted event log so they survive client reconnects and full
backend restarts. Request models live in ``runs_models`` and SSE streaming
helpers in ``runs_events``.

This module owns run create/list/read, the SSE stream, and the chat
endpoints, and assembles the full route set by including the sibling
endpoint routers -- ``runs_lifecycle`` (start/cancel/pause/resume and the
startup auto-resume launcher), ``runs_collections`` (read-only collection
getters, safety adjudication, reports), and ``runs_contrib``
(scientist-contributed hypotheses/reviews/attachments), with shared
existence guards in ``runs_support``. Every moved name is re-exported
here so ``app.runs`` remains the stable import and monkeypatch surface.
"""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.responses import JSONResponse, StreamingResponse

from app import (
    engine_adapter,
    engine_tasks,
    paper_corpus,
    qa,
    runs_collections,
    runs_contrib,
    runs_lifecycle,
    store,
)
from app.audience import audience_chat_context
from app.auth import client_id
from app.runs_collections import (
    adjudicate_safety as adjudicate_safety,
)
from app.runs_collections import (
    get_citations as get_citations,
)
from app.runs_collections import (
    get_claim_evidence as get_claim_evidence,
)
from app.runs_collections import (
    get_evidence as get_evidence,
)
from app.runs_collections import (
    get_hypotheses as get_hypotheses,
)
from app.runs_collections import (
    get_matches as get_matches,
)
from app.runs_collections import (
    get_metrics as get_metrics,
)
from app.runs_collections import (
    get_proximity as get_proximity,
)
from app.runs_collections import (
    get_report as get_report,
)
from app.runs_collections import (
    get_report_markdown as get_report_markdown,
)
from app.runs_collections import (
    get_reviews as get_reviews,
)
from app.runs_collections import (
    get_run_logs as get_run_logs,
)
from app.runs_collections import (
    get_safety as get_safety,
)
from app.runs_contrib import (
    add_attachment as add_attachment,
)
from app.runs_contrib import (
    add_human_hypothesis as add_human_hypothesis,
)
from app.runs_contrib import (
    add_human_review as add_human_review,
)
from app.runs_contrib import (
    search_attachments as search_attachments,
)
from app.runs_contrib import (
    upload_attachment as upload_attachment,
)
from app.runs_events import _event_stream
from app.runs_lifecycle import (
    _check_startable as _check_startable,
)
from app.runs_lifecycle import (
    _has_paused_engine_task as _has_paused_engine_task,
)
from app.runs_lifecycle import (
    _launch_resume as _launch_resume,
)
from app.runs_lifecycle import (
    _log_resume_task_result as _log_resume_task_result,
)
from app.runs_lifecycle import (
    _resume_tasks as _resume_tasks,
)
from app.runs_lifecycle import (
    cancel_run as cancel_run,
)
from app.runs_lifecycle import (
    pause_run as pause_run,
)
from app.runs_lifecycle import (
    resume_interrupted_runs as resume_interrupted_runs,
)
from app.runs_lifecycle import (
    resume_run as resume_run,
)
from app.runs_lifecycle import (
    start_run as start_run,
)
from app.runs_models import (
    AskRequest,
    CreateRunRequest,
    SendMessageRequest,
    _build_create_run_config,
)
from app.runs_models import (
    HumanAttachmentRequest as HumanAttachmentRequest,
)
from app.runs_models import (
    HumanHypothesisRequest as HumanHypothesisRequest,
)
from app.runs_models import (
    HumanReviewRequest as HumanReviewRequest,
)
from app.runs_models import (
    SafetyAdjudicationRequest as SafetyAdjudicationRequest,
)
from app.runs_models import (
    StartRunRequest as StartRunRequest,
)
from app.runs_support import (
    _require_run as _require_run,
)
from app.runs_support import (
    _run_or_404 as _run_or_404,
)
from app.store import RunStatus
from app.title_gen import generate_run_title

router = APIRouter(prefix="/api/runs", tags=["runs"])


# ---------------------------------------------------------------------------
# Create / list / read
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


def _resolve_run_interview(
    req: CreateRunRequest, request: Request
) -> tuple[dict[str, Any] | None, CreateRunRequest]:
    """Validate req.interview_id and merge its fields into the request.

    Returns the interview record (or None if unset) and the possibly
    updated request.
    """
    if not req.interview_id:
        return None, req
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
    return interview, req


def _build_run_config(
    req: CreateRunRequest, interview: dict[str, Any] | None
) -> tuple[dict[str, Any], str, str]:
    """Build the run config, folding in notification and interview settings."""
    config, focus, tier = _build_create_run_config(req)
    if req.notify_on_completion and req.completion_email:
        config["completion_notification"] = {
            "enabled": True,
            "email": req.completion_email,
        }
    if interview is not None:
        config["interview_id"] = interview["id"]
    return config, focus, tier


def _persist_new_run(
    req: CreateRunRequest,
    request: Request,
    interview: dict[str, Any] | None,
    config: dict[str, Any],
    run_mode: str,
    provider: str,
    focus: str,
    llm_backend: str,
) -> store.RunRow:
    """Create the DRAFT run row and log its creation event.

    The run is persisted in DRAFT; nothing executes until /start is called.
    """
    run = store.create_run(
        research_goal=req.research_goal,
        profile=run_mode,
        provider=provider,
        config=config,
        client_id=client_id(request),
        title=(interview["fields"].get("title") if interview else None),
        llm_backend=llm_backend,
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
            "tier": run_mode,
        },
    )
    return run


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
    interview, req = _resolve_run_interview(req, request)

    # The engine is the only provider; select_provider() raises if it is not
    # importable rather than falling back to anything else. The LLM backend
    # is recorded separately: the process offline predicate decides whether
    # this run's science runs against the deterministic offline router.
    provider = engine_adapter.select_provider()
    llm_backend = "offline" if engine_adapter.offline_mode() else "real"
    config, focus, tier = _build_run_config(req, interview)
    run = _persist_new_run(
        req, request, interview, config, tier, provider, focus, llm_backend
    )
    # Title generation needs a real model, so only when a provider credential
    # is configured: offline/keyless runs keep the goal-clause fallback.
    if not engine_adapter.offline_mode():
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


# Lifecycle endpoints (start/cancel/pause/resume) live in runs_lifecycle.
router.include_router(runs_lifecycle.router)


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


# Read-only collection/report endpoints live in runs_collections; the
# scientist-contribution endpoints (hypotheses/reviews/attachments) in
# runs_contrib.
router.include_router(runs_collections.router)
router.include_router(runs_contrib.router)


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


def _gather_qa_context(
    run_id: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[Any],
    list[dict[str, Any]],
]:
    """Load a run's state and build its numbered evidence manifest for Q&A."""
    # All six reads target the same run; share one connection.
    with store.connect() as conn:
        hypotheses = store.list_hypotheses(run_id, conn=conn)
        reviews = store.list_reviews(run_id, conn=conn)
        matches = store.list_matches(run_id, conn=conn)
        # [:-1] drops the question just appended above from the history.
        history = store.list_messages(run_id, conn=conn)[:-1]
        evidence = store.list_evidence(run_id, conn=conn)
        citations = store.list_citations(run_id, conn=conn)
    manifest = qa.build_evidence_manifest(evidence, citations)
    return hypotheses, reviews, matches, history, manifest


def _offline_qa_response(
    run: store.RunRow,
    run_id: str,
    question_msg: store.MessageRow,
    hypotheses: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    manifest: list[dict[str, Any]],
) -> StreamingResponse:
    """Synthesize and stream a deterministic offline-mode Q&A answer.

    Keyless/offline posture: with no configured provider there is no
    language model to call, so synthesize a deterministic answer grounded in
    the run's own artifacts rather than streaming an API-key error. The real
    LLM path is unchanged for a configured provider.
    """
    answer = qa.build_offline_answer(
        run.research_goal, hypotheses, reviews, manifest
    )
    return StreamingResponse(
        qa.stream_offline_answer(run_id, question_msg.id, answer, manifest),
        media_type="text/event-stream",
    )


@router.post("/{run_id}/messages/ask")
async def ask_question(run_id: str, req: AskRequest) -> StreamingResponse:
    """Answer a question about the run using a fast LLM.

    The response is streamed back to the caller.
    """
    run = _run_or_404(run_id)

    # Persist the question first so history survives even if streaming fails.
    question_msg = store.append_message(run_id, "user", req.question, "qa")

    # Prompt assembly and streaming are delegated to qa.py; the endpoint
    # only gathers state and wires the SSE response.
    hypotheses, reviews, matches, history, manifest = _gather_qa_context(run_id)

    if engine_adapter.offline_mode():
        return _offline_qa_response(
            run, run_id, question_msg, hypotheses, reviews, manifest
        )

    system_prompt = qa.build_system_prompt(
        run.research_goal,
        hypotheses,
        reviews,
        matches,
        history,
        manifest,
        audience_context=audience_chat_context(req.audience),
        corpus_catalog=paper_corpus.catalog_context(req.audience),
    )
    return StreamingResponse(
        qa.stream_answer(
            run_id, req.question, question_msg.id, system_prompt, manifest
        ),
        media_type="text/event-stream",
    )
