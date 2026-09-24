"""Run lifecycle router.

Endpoints:
- POST   /api/runs                        create a draft run
- GET    /api/runs                        list runs (most recent first)
- GET    /api/runs/{id}                   read run + summary counts
- POST   /api/runs/{id}/start             start the workflow (background)
- POST   /api/runs/{id}/cancel            cancel a running workflow
- DELETE /api/runs/{id}                   permanently delete a terminal run
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
- GET    /api/runs/{id}/report.md         Goal Report document (markdown)

Cancellation revokes queued and leased tasks; pause parks queued work while
leased tasks may finish, with engine claims held until resume. Streams use
the persisted event log so they survive client reconnects and full
backend restarts. Request models live in ``runs_models`` and SSE streaming
helpers in ``runs_events``.

This module owns the SSE stream and assembles the full route set by
including the sibling endpoint routers -- ``runs_crud`` (create/list/read),
``runs_lifecycle`` (start/cancel/pause/resume and the startup auto-resume
launcher), ``runs_collections`` (read-only collection getters, safety
adjudication, reports), ``runs_contrib`` (scientist-contributed
hypotheses/reviews/attachments), and ``runs_chat`` (steering messages and
grounded Q&A), with shared existence guards in ``runs_support``. Every
moved name is re-exported here so ``app.runs`` remains the stable import
and monkeypatch surface.
"""

from __future__ import annotations

from typing import Any as Any

from fastapi import (
    APIRouter,
    Query,
    Request,
    Response,
)
from fastapi import (
    BackgroundTasks as BackgroundTasks,
)
from fastapi import (
    HTTPException as HTTPException,
)
from fastapi.responses import JSONResponse, StreamingResponse

from app import (
    engine_adapter as engine_adapter,
)
from app import (
    engine_tasks as engine_tasks,
)
from app import (
    qa as qa,
)
from app import (
    runs_chat,
    runs_collections,
    runs_contrib,
    runs_crud,
    runs_deletion,
    runs_lifecycle,
    store,
)
from app.auth import client_id as client_id
from app.runs_chat import (
    _gather_qa_context as _gather_qa_context,
)
from app.runs_chat import (
    _offline_qa_response as _offline_qa_response,
)
from app.runs_chat import (
    announce_start as announce_start,
)
from app.runs_chat import (
    ask_question as ask_question,
)
from app.runs_chat import (
    list_messages as list_messages,
)
from app.runs_chat import (
    send_message as send_message,
)
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
    get_hypothesis_outcomes as get_hypothesis_outcomes,
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
from app.runs_collections import (
    get_tasks as get_tasks,
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
    record_hypothesis_outcome as record_hypothesis_outcome,
)
from app.runs_contrib import (
    search_attachments as search_attachments,
)
from app.runs_contrib import (
    upload_attachment as upload_attachment,
)
from app.runs_crud import (
    _build_run_config as _build_run_config,
)
from app.runs_crud import (
    _persist_new_run as _persist_new_run,
)
from app.runs_crud import (
    _populate_run_title as _populate_run_title,
)
from app.runs_crud import (
    _resolve_run_interview as _resolve_run_interview,
)
from app.runs_crud import (
    _runs_payload as _runs_payload,
)
from app.runs_crud import (
    create_run as create_run,
)
from app.runs_crud import (
    get_run as get_run,
)
from app.runs_crud import (
    list_demo_runs as list_demo_runs,
)
from app.runs_crud import (
    list_runs as list_runs,
)
from app.runs_crud import (
    rename_run as rename_run,
)
from app.runs_deletion import (
    delete_run as delete_run,
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
    AskRequest as AskRequest,
)
from app.runs_models import (
    CreateRunRequest as CreateRunRequest,
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
    SendMessageRequest as SendMessageRequest,
)
from app.runs_models import (
    StartRunRequest as StartRunRequest,
)
from app.runs_models import (
    _build_create_run_config as _build_create_run_config,
)
from app.runs_support import (
    _require_run as _require_run,
)
from app.runs_support import (
    _run_or_404 as _run_or_404,
)
from app.store import RunStatus as RunStatus
from app.title_gen import generate_run_title as generate_run_title

router = APIRouter(prefix="/api/runs", tags=["runs"])


# Create/list/read endpoints live in runs_crud. They register directly on
# this router (a prefix-less sub-router cannot carry the empty "" paths),
# in the original order: /demo before /{run_id} so the literal path keeps
# winning route matching.
router.post("")(runs_crud.create_run)
router.get("")(runs_crud.list_runs)
router.get("/demo")(runs_crud.list_demo_runs)
router.get("/{run_id}")(runs_crud.get_run)
router.patch("/{run_id}")(runs_crud.rename_run)

# Lifecycle endpoints (start/cancel/pause/resume) live in runs_lifecycle.
router.include_router(runs_lifecycle.router)

# Permanent deletion lives in runs_deletion.
router.include_router(runs_deletion.router)


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
# runs_contrib; the chat/interaction endpoints (steering messages and
# grounded Q&A) in runs_chat.
router.include_router(runs_collections.router)
router.include_router(runs_contrib.router)
router.include_router(runs_chat.router)
