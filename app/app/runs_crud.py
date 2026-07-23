"""Run create/list/read endpoints.

The draft-run creation flow (interview merge, config assembly, DRAFT row
persistence, background title generation) plus the run list and detail
reads. Split from ``app.runs`` by concern, matching the sibling endpoint
modules (``runs_lifecycle``, ``runs_collections``, ``runs_contrib``).
Unlike those siblings this module carries no router of its own: FastAPI
rejects the empty ``""`` create/list paths on a prefix-less sub-router, so
``app.runs`` registers these handlers directly on ``runs.router`` (in the
original order, keeping ``/demo`` ahead of ``/{run_id}``) and re-exports
every name, remaining the stable import and monkeypatch surface.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from fastapi import (
    BackgroundTasks,
    HTTPException,
    Query,
    Request,
)

from app import engine_adapter, store
from app.auth import client_id
from app.runs_models import CreateRunRequest, _build_create_run_config
from app.runs_support import _run_or_404
from app.store import RunStatus
from app.title_gen import generate_run_title


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


class _ResolvedRunSettings(NamedTuple):
    """The settings a new run is persisted with, resolved from its request."""

    config: dict[str, Any]
    run_mode: str
    provider: str
    focus: str
    llm_backend: str


def _resolve_run_settings(
    req: CreateRunRequest, interview: dict[str, Any] | None
) -> _ResolvedRunSettings:
    """Resolve the provider, LLM backend, and config for a new run.

    The engine is the only provider; select_provider() raises if it is not
    importable rather than falling back to anything else. The LLM backend is
    recorded separately: the process offline predicate decides whether this
    run's science runs against the deterministic offline router.

    Args:
        req: Request body with the research goal, run mode, and run config.
        interview: The merged goal interview, when the run came from one.

    Returns:
        Everything ``_persist_new_run`` writes onto the DRAFT row.
    """
    provider = engine_adapter.select_provider()
    llm_backend = "offline" if engine_adapter.offline_mode() else "real"
    config, focus, tier = _build_run_config(req, interview)
    return _ResolvedRunSettings(
        config=config,
        run_mode=tier,
        provider=provider,
        focus=focus,
        llm_backend=llm_backend,
    )


def _persist_new_run(
    req: CreateRunRequest,
    request: Request,
    interview: dict[str, Any] | None,
    resolved: _ResolvedRunSettings,
) -> store.RunRow:
    """Create the DRAFT run row and log its creation event.

    The run is persisted in DRAFT; nothing executes until /start is called.
    """
    run = store.create_run(
        req.research_goal,
        resolved.run_mode,
        resolved.provider,
        resolved.config,
        store.RunCreateOptions(
            client_id=client_id(request),
            title=interview["fields"].get("title") if interview else None,
            llm_backend=resolved.llm_backend,
        ),
    )
    # First entry in the run's event log, so replays show creation metadata.
    store.append_event(
        run.id,
        "lifecycle",
        {
            "event": "created",
            "run_mode": resolved.run_mode,
            "provider": resolved.provider,
            "focus": resolved.focus,
            "tier": resolved.run_mode,
        },
    )
    return run


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
    run = _persist_new_run(
        req, request, interview, _resolve_run_settings(req, interview)
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


async def list_runs(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    """List the requesting client's runs, most recent first."""
    runs = store.list_runs(client_id=client_id(request), limit=limit)
    return _runs_payload(runs)


# app.runs registers this before /{run_id} so the literal path wins route
# matching.
async def list_demo_runs() -> dict[str, Any]:
    """List the seeded demo runs, which are visible to every client."""
    runs = store.list_runs(client_id=store.DEMO_CLIENT_ID)
    return _runs_payload(runs)


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
