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

from app import (
    credentials,
    documents,
    engine_adapter,
    paper_corpus,
    run_corpus,
    store,
)
from app.auth import client_id, principal_for_request, require_client_scope
from app.config import byok_enabled
from app.runs_models import CreateRunRequest, _build_create_run_config
from app.runs_support import _run_or_404
from app.store import RunStatus
from app.title_gen import generate_run_title


async def _populate_run_title(
    run_id: str,
    goal: str,
    byok: credentials.ByokCredential | None = None,
) -> None:
    """Generate a run's short session title and persist it (best-effort).

    Runs after the create response as a background task, so the create call
    isn't blocked on a model round-trip. A None result (generation
    unavailable) leaves the title unset and surfaces fall back to a clause of
    the goal. A bring-your-own-key run titles under its own credential.

    Args:
        run_id: The run to title.
        goal: The run's research goal.
        byok: The run's credential, when it was created with one.
    """
    with credentials.scoped_byok(byok):
        title = await generate_run_title(goal)
    if title:
        store.set_run_title(run_id, title)


async def _resolve_byok(request: Request) -> credentials.ByokCredential | None:
    """Parse and validate the BYOK headers, refusing bad pairs up front.

    The cheap live validation call happens here, BEFORE any database
    write, so a rejected key costs a run row nothing and the store's
    writer is never held across the network call.

    Args:
        request: The create-run request carrying the BYOK headers.

    Returns:
        The validated credential, or None when no key was sent.

    Raises:
        HTTPException: 400 for a malformed pair or a key the provider
            rejects (worded exactly as a rejection), 503 when this
            deployment has no BYOK encryption secret configured.
    """
    try:
        credential = credentials.credential_from_headers(request.headers)
    except credentials.ByokRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if credential is None:
        return None
    if not byok_enabled():
        raise HTTPException(
            status_code=503,
            detail=("this deployment does not accept bring-your-own-key runs"),
        )
    try:
        await credentials.validate_byok_credential(credential)
    except credentials.ByokValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return credential


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
    req: CreateRunRequest,
    interview: dict[str, Any] | None,
    byok: credentials.ByokCredential | None = None,
) -> _ResolvedRunSettings:
    """Resolve the provider, LLM backend, and config for a new run.

    The engine is the only provider; select_provider() raises if it is not
    importable rather than falling back to anything else. The LLM backend is
    recorded separately: the process offline predicate decides whether this
    run's science runs against the deterministic offline router -- except a
    bring-your-own-key run, which is always real-backed (its validated key
    must not be shadowed by the router) and records its provider in the
    config so every later backend resolution sees it.

    Args:
        req: Request body with the research goal, run mode, and run config.
        interview: The merged goal interview, when the run came from one.
        byok: The validated bring-your-own-key credential, when sent.

    Returns:
        Everything ``_persist_new_run`` writes onto the DRAFT row.
    """
    provider = engine_adapter.select_provider()
    if byok is not None:
        llm_backend = "real"
    else:
        llm_backend = "offline" if engine_adapter.offline_mode() else "real"
    config, focus, tier = _build_run_config(req, interview)
    if byok is not None:
        # A flag only -- never the key. resolve_offline_backend and the
        # generator construction both read it to keep the run real-backed.
        config["byok_provider"] = byok.provider
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


def _run_setup_documents(
    req: CreateRunRequest, interview: dict[str, Any] | None, owner: str
) -> list[dict[str, Any]]:
    """Resolve every staged document this run is to be created with.

    The union of the documents named on the request and those already
    attached to its chat, de-duplicated by id and ordered as staged.

    Raises:
        HTTPException: 404 when a named document is unknown or unowned.
    """
    named = documents.resolve_owned_documents(req.document_ids, owner)
    from_chat = (
        store.list_interview_documents(str(interview["id"]))
        if interview is not None
        else []
    )
    resolved: dict[str, dict[str, Any]] = {}
    for document in [*named, *from_chat]:
        resolved.setdefault(str(document["id"]), document)
    return list(resolved.values())


def _index_setup_documents(run_id: str, staged: list[dict[str, Any]]) -> None:
    """Copy staged documents into the new run's private corpus.

    Indexed with the same source marker an in-run upload uses, so the
    run-scoped retriever and the report's provenance cannot tell a document
    attached at setup from one attached later -- only the timing differs.
    """
    for document in staged:
        store.add_evidence(
            store.NewEvidence(
                run_id=run_id,
                title=str(document["title"]),
                source=run_corpus.ATTACHMENT_SOURCE,
                abstract=str(document["text"]),
                mime_type=str(document["mime_type"]),
                sha256=str(document["sha256"]),
                byte_size=int(document["byte_size"]),
                document_version=str(document["sha256"]),
                extraction_tool=str(document["extraction_tool"]),
            )
        )
    store.mark_documents_used_by_run(run_id, [str(d["id"]) for d in staged])


async def create_run(
    req: CreateRunRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Create a new run for the requesting client and return it.

    Creation is the single committing step of run setup: the credential and
    every attached document are resolved BEFORE the run row is written, so a
    request that cannot be satisfied leaves nothing behind. Uploading
    attachments after creation instead made setup a three-call sequence
    whose middle step could fail, stranding a created, unstarted, ungrounded
    run that nothing named.

    Args:
        req: Request body with the research goal, run mode, and run config.
        request: Incoming HTTP request, used to read the client identifier.
        background_tasks: FastAPI background queue used to generate the run's
            session title off the request's critical path.

    Returns:
        The created run serialized as a dict.

    Raises:
        HTTPException: 400 when the caller carries no identity at all (a
            compatibility caller sending no ``X-Client-ID`` header) --
            checked first and before any other work, since a run created
            under that scope would be invisible to its own creator (see
            ``app.auth.require_client_scope``).
    """
    require_client_scope(request)
    # The corpus audience gates real content (see paper_corpus.py), so a
    # claim the caller cannot back with a verified researcher session is
    # downgraded before anything else reads req.audience -- the config,
    # the injected catalog, and the persisted run row all derive from this.
    principal = principal_for_request(request)
    req = req.model_copy(
        update={
            "audience": paper_corpus.verified_audience(
                req.audience, principal.method if principal else None
            )
        }
    )
    # Validated BEFORE any database write: a rejected key must surface as
    # a clean 4xx here, never as a stored run that fails mid-execution.
    byok = await _resolve_byok(request)
    interview, req = _resolve_run_interview(req, request)
    staged = _run_setup_documents(req, interview, client_id(request))
    run = _persist_new_run(
        req,
        request,
        interview,
        _resolve_run_settings(req, interview, byok),
    )
    _index_setup_documents(run.id, staged)
    if byok is not None:
        credentials.store_run_credential(run.id, run.client_id, byok)
    # Title generation needs a real model: either the run brought its own
    # key or the deployment has one. Offline/keyless runs keep the
    # goal-clause fallback.
    if byok is not None or not engine_adapter.offline_mode():
        background_tasks.add_task(
            _populate_run_title, run.id, req.research_goal, byok
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
    """List the requesting client's runs, most recent first.

    An identity-less compatibility caller (no ``X-Client-ID`` header) owns
    nothing -- ``create_run`` refuses that caller a run of its own -- so
    its list is always empty rather than querying a scope that could only
    ever match legacy rows predating that guard.
    """
    subject = client_id(request)
    if not subject:
        return {"runs": []}
    runs = store.list_runs(client_id=subject, limit=limit)
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
