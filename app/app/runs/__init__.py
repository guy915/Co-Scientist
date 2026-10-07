from __future__ import annotations

from fastapi import (
    APIRouter,
    Query,
    Request,
    Response,
)
from fastapi.responses import JSONResponse, StreamingResponse

import app.runs.crud as runs_deletion
from app.api_contracts import RunsResponse
from app.api_contracts.runs import Run, RunWithSummary
from app.async_bridge import off_loop
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
from app.store import events as store

router = APIRouter(prefix="/api/runs", tags=["runs"])


# Literal /demo routes precede /{run_id} so first-match routing cannot consume
# them as
# IDs.
router.post("", response_model=Run)(runs_crud.create_run)
router.get("", response_model=RunsResponse)(runs_crud.list_runs)
router.get("/demo", response_model=RunsResponse)(runs_crud.list_demo_runs)
router.get("/{run_id}", response_model=RunWithSummary)(runs_crud.get_run)
router.patch("/{run_id}", response_model=RunWithSummary)(runs_crud.rename_run)

router.include_router(runs_lifecycle.router)

router.include_router(runs_deletion.router)


@router.get("/{run_id}/events")
@off_loop
def stream_events(
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
            # Proxy buffering would prevent incremental SSE delivery.
            "X-Accel-Buffering": "no",
        },
    )


router.include_router(runs_collections.router)
router.include_router(runs_contrib.router)
router.include_router(runs_chat.router)
