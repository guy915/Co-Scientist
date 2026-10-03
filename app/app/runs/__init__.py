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
backend restarts. Request models live in ``runs.models`` and SSE streaming
helpers in ``runs.events``.

This module owns the SSE stream and assembles the full route set by
including the sibling endpoint routers -- ``runs.crud`` (create/list/read),
``runs.lifecycle`` (start/cancel/pause/resume and the startup auto-resume
launcher; the safety-adjudication handler it drives lives in
``runs.lifecycle_adjudication``), ``runs.collections`` (read-only collection
getters and reports, plus the registration of that handler at its historical
slot), ``runs.contrib`` (scientist-contributed
hypotheses/reviews/attachments), and ``runs.chat`` (steering messages and
grounded Q&A), with shared existence guards in ``runs.support``. The
moved names that callers and tests use are re-exported here so
``app.runs`` remains their import and monkeypatch surface.
"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Query,
    Request,
    Response,
)
from fastapi.responses import JSONResponse, StreamingResponse

import app.runs.crud as runs_deletion
from app import store
from app.api_contracts.responses import RunsResponse
from app.api_contracts.runs import Run, RunWithSummary
from app.runs import chat as runs_chat
from app.runs import collections as runs_collections
from app.runs import contrib as runs_contrib
from app.runs import crud as runs_crud
from app.runs import lifecycle as runs_lifecycle
from app.runs.events import _event_stream
from app.runs.lifecycle import (
    resume_interrupted_runs as resume_interrupted_runs,
)
from app.runs.support import (
    _run_or_404 as _run_or_404,
)

router = APIRouter(prefix="/api/runs", tags=["runs"])


# Create/list/read endpoints live in runs.crud. They register directly on
# this router (a prefix-less sub-router cannot carry the empty "" paths),
# in the original order: /demo before /{run_id} so the literal path keeps
# winning route matching.
router.post("", response_model=Run)(runs_crud.create_run)
router.get("", response_model=RunsResponse)(runs_crud.list_runs)
router.get("/demo", response_model=RunsResponse)(runs_crud.list_demo_runs)
router.get("/{run_id}", response_model=RunWithSummary)(runs_crud.get_run)
router.patch("/{run_id}", response_model=RunWithSummary)(runs_crud.rename_run)

# Lifecycle endpoints (start/cancel/pause/resume) live in runs.lifecycle.
router.include_router(runs_lifecycle.router)

# Permanent deletion lives in runs.deletion.
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


# Read-only collection/report endpoints live in runs.collections; the
# scientist-contribution endpoints (hypotheses/reviews/attachments) in
# runs.contrib; the chat/interaction endpoints (steering messages and
# grounded Q&A) in runs.chat.
router.include_router(runs_collections.router)
router.include_router(runs_contrib.router)
router.include_router(runs_chat.router)
