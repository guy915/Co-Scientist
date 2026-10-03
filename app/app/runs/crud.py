"""Run create/list/read endpoints."""

from __future__ import annotations

import sqlite3
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, NamedTuple, Protocol

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

import app.credentials as credentials
import app.engine_adapter as engine_adapter
import app.free_usage as free_usage
import app.run_corpus as run_corpus
import app.staged_documents as staged_documents
import app.store as store
import app.store.receipts as run_creation_receipts
from app.auth import client_id, require_client_scope
from app.config import byok_enabled
from app.execution_policy import (
    CAMPAIGN,
    CAMPAIGN_MODEL_CONFIG_KEY,
    CAMPAIGN_MODEL_NAME,
    campaign_model_for_config,
    resolve_execution_policy,
    scoped_execution_policy,
)
from app.goal_text import (
    clean_title,
    generate_goal_restatement,
    generate_run_title,
)
from app.runs.models import (
    CreateRunRequest,
    RenameRunRequest,
    _build_create_run_config,
)
from app.runs.support import _run_or_404
from app.store import RunRow, RunStatus


def _reject_campaign_byok(
    credential: credentials.ByokCredential | None, execution_policy: str
) -> None:
    """Refuse paid caller credentials for a server-funded campaign."""
    if credential is not None and execution_policy == CAMPAIGN:
        raise HTTPException(
            status_code=400,
            detail="campaign runs cannot use bring-your-own-key credentials",
        )


async def _resolve_byok(
    request: Request, execution_policy: str = "standard"
) -> credentials.ByokCredential | None:
    """Parse and validate the BYOK headers, refusing bad pairs up front.

    The cheap live validation call happens here, BEFORE any database
    write, so a rejected key costs a run row nothing and the store's
    writer is never held across the network call.

    Args:
        request: The create-run request carrying the BYOK headers.
        execution_policy: Trusted policy derived from the caller/interview.

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
    _reject_campaign_byok(credential, execution_policy)
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


class _PersistNewRun(Protocol):
    def __call__(  # noqa: PLR0913 -- mirrors the persisted run and initial event.
        self,
        req: CreateRunRequest,
        request: Request,
        interview: dict[str, Any] | None,
        resolved: _ResolvedRunSettings,
        execution_policy: str = "standard",
        *,
        conn: sqlite3.Connection | None = None,
    ) -> store.RunRow: ...


@dataclass(frozen=True)
class RunCreationCallbacks:
    """Patchable helpers provided by the registered route module."""

    require_client_scope: Callable[[Request], str]
    client_id: Callable[[Request], str]
    resolve_execution_policy: Callable[[Request, dict[str, Any] | None], str]
    scoped_execution_policy: Callable[[str], AbstractContextManager[None]]
    resolve_byok: Callable[
        [Request, str], Awaitable[credentials.ByokCredential | None]
    ]
    resolve_run_interview: Callable[
        [CreateRunRequest, Request],
        tuple[dict[str, Any] | None, CreateRunRequest],
    ]
    resolve_run_settings: Callable[
        [
            CreateRunRequest,
            dict[str, Any] | None,
            credentials.ByokCredential | None,
        ],
        _ResolvedRunSettings,
    ]
    persist_new_run: _PersistNewRun
    run_setup_documents: Callable[
        [CreateRunRequest, dict[str, Any] | None, str],
        list[dict[str, Any]],
    ]
    post_commit_effects: Callable[
        [
            store.RunRow,
            CreateRunRequest,
            credentials.ByokCredential | None,
            BackgroundTasks,
        ],
        None,
    ]


def _receipt_replay(
    receipt: run_creation_receipts.RunCreationReceipt | None,
    request_digest: str,
) -> store.RunRow | None:
    """Return the current owned run or raise the matching replay error."""
    if receipt is None:
        return None
    if receipt.request_digest != request_digest:
        raise HTTPException(409, "Idempotency-Key was used for another request")
    if receipt.run is None:
        raise HTTPException(404, "run not found")
    return receipt.run


def _persist_new_run_for_owner(  # noqa: PLR0913 -- these values define one run and its first event.
    req: CreateRunRequest,
    request: Request,
    interview: dict[str, Any] | None,
    resolved: _ResolvedRunSettings,
    execution_policy: str = "standard",
    *,
    owner: str,
    conn: sqlite3.Connection | None = None,
) -> store.RunRow:
    """Create the DRAFT row and first event, bounding any interview title."""
    interview_title = None
    if interview:
        interview_title = clean_title(interview["fields"].get("title") or "")
    run = store.create_run(
        req.research_goal,
        resolved.run_mode,
        resolved.provider,
        resolved.config,
        store.RunCreateOptions(
            client_id=owner,
            title=interview_title,
            llm_backend=resolved.llm_backend,
            execution_policy=execution_policy,
            conn=conn,
            log_created=conn is None,
        ),
    )
    event = {"event": "created"}
    event["run_mode"] = resolved.run_mode
    event["provider"] = resolved.provider
    event["focus"] = resolved.focus
    event["tier"] = resolved.run_mode
    if conn is None:
        store.append_event(run.id, "lifecycle", event)
    else:
        store.append_event_deferred_log(run.id, "lifecycle", event, conn)
    return run


def _run_setup_documents(
    req: CreateRunRequest, interview: dict[str, Any] | None, owner: str
) -> list[dict[str, Any]]:
    """Resolve named and interview attachments in staged order."""
    named = staged_documents.resolve_owned_documents(req.document_ids, owner)
    return store.merge_run_setup_documents(
        named, str(interview["id"]) if interview is not None else None
    )


@dataclass(frozen=True)
class _Admission:
    owner: str
    idempotency_key: str | None
    request_digest: str | None
    replay: dict[str, Any] | None


@dataclass(frozen=True)
class _ResolvedSetup:
    request: CreateRunRequest
    interview: dict[str, Any] | None
    execution_policy: str
    byok: credentials.ByokCredential | None
    staged_documents: list[dict[str, Any]]
    settings: _ResolvedRunSettings
    free_usage: bool = False


def _admit_request(
    req: CreateRunRequest,
    request: Request,
    callbacks: RunCreationCallbacks,
) -> _Admission:
    """Validate identity and return an existing receipt before setup reads."""
    callbacks.require_client_scope(request)
    owner = callbacks.client_id(request)
    key = request.headers.get("Idempotency-Key")
    if key is not None and not (
        run_creation_receipts.valid_run_creation_key(key)
    ):
        raise HTTPException(
            400,
            "Idempotency-Key must match [A-Za-z0-9._~-] and be 1-128 chars",
        )
    digest = None
    if key is not None:
        try:
            digest = credentials.run_creation_request_digest(
                req.model_dump(mode="json"),
                api_key=request.headers.get(credentials.API_KEY_HEADER),
                provider=request.headers.get(credentials.PROVIDER_HEADER),
            )
        except credentials.ByokNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        receipt = run_creation_receipts.lookup_run_creation_receipt(owner, key)
        replay = _receipt_replay(receipt, digest)
        if replay is not None:
            return _Admission(owner, key, digest, replay.to_dict())
    return _Admission(owner, key, digest, None)


async def _resolve_setup(
    req: CreateRunRequest,
    request: Request,
    owner: str,
    callbacks: RunCreationCallbacks,
) -> _ResolvedSetup:
    """Resolve mutable interview, credential, document, and run settings."""
    interview, resolved_request = callbacks.resolve_run_interview(req, request)
    policy = callbacks.resolve_execution_policy(request, interview)
    with callbacks.scoped_execution_policy(policy):
        byok = await callbacks.resolve_byok(request, policy)
    staged = callbacks.run_setup_documents(resolved_request, interview, owner)
    settings = callbacks.resolve_run_settings(resolved_request, interview, byok)
    if policy == CAMPAIGN:
        settings = settings._replace(
            config={
                **settings.config,
                CAMPAIGN_MODEL_CONFIG_KEY: CAMPAIGN_MODEL_NAME,
            }
        )
    free = free_usage.applies(byok, policy, settings.llm_backend)
    if free and resolved_request.tier is None:
        # Free usage defaults to the one tier it may run.
        resolved_request = resolved_request.model_copy(
            update={"tier": free_usage.FREE_TIER}
        )
        settings = callbacks.resolve_run_settings(
            resolved_request, interview, byok
        )
    if free:
        free_usage.check_request(resolved_request, settings.run_mode)
    return _ResolvedSetup(
        resolved_request, interview, policy, byok, staged, settings, free
    )


def _persist_setup_transaction(
    admission: _Admission,
    setup: _ResolvedSetup,
    request: Request,
    callbacks: RunCreationCallbacks,
) -> tuple[
    store.RunRow | None,
    run_creation_receipts.RunCreationReceipt | None,
]:
    """Write setup atomically, mapping a raced-away document to HTTP 404."""

    def persist_run(conn: sqlite3.Connection) -> store.RunRow:
        run = callbacks.persist_new_run(
            setup.request,
            request,
            setup.interview,
            setup.settings,
            setup.execution_policy,
            conn=conn,
        )
        if setup.free_usage:
            free_usage.claim_free_run(conn, admission.owner, run.id)
        return run

    try:
        run, receipt = run_creation_receipts.commit_run_creation(
            admission.owner,
            admission.idempotency_key,
            admission.request_digest,
            setup.staged_documents,
            setup.byok,
            persist_run,
            run_corpus.ATTACHMENT_SOURCE,
        )
    except run_creation_receipts.StagedDocumentsUnavailableError as exc:
        raise HTTPException(
            status_code=404, detail="attached document not found"
        ) from exc
    except free_usage.FreeUsageExhaustedError as exc:
        raise free_usage.exhausted_error() from exc
    return run, receipt


def _commit_setup(
    admission: _Admission,
    setup: _ResolvedSetup,
    request: Request,
    callbacks: RunCreationCallbacks,
) -> tuple[store.RunRow, bool]:
    """Resolve a concurrent replay and mirror only newly committed logs."""
    run, receipt = _persist_setup_transaction(
        admission, setup, request, callbacks
    )
    if receipt is not None:
        replay = _receipt_replay(receipt, admission.request_digest or "")
        if replay is not None:
            return replay, False
    if run is None:
        raise RuntimeError("run creation returned no run or receipt")
    store.log_run_created(run)
    store.log_event_stage(
        run.id,
        "lifecycle",
        {
            "event": "created",
            "run_mode": setup.settings.run_mode,
            "provider": setup.settings.provider,
            "focus": setup.settings.focus,
            "tier": setup.settings.run_mode,
        },
    )
    return run, True


async def _create_run_with_callbacks(
    req: CreateRunRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    callbacks: RunCreationCallbacks,
) -> dict[str, Any]:
    """Admit, resolve, atomically persist, and serialize one new run."""
    admission = _admit_request(req, request, callbacks)
    if admission.replay is not None:
        return admission.replay
    setup = await _resolve_setup(req, request, admission.owner, callbacks)
    run, created = _commit_setup(admission, setup, request, callbacks)
    if created:
        callbacks.post_commit_effects(
            run, setup.request, setup.byok, background_tasks
        )
    return run.to_dict()


router = APIRouter()

# Statuses with a live or claimable worker lease. Everything else -- draft
# (never started), paused (its task is parked, not leased), and every
# terminal status -- has no in-flight writer to race, so deletion is safe.
# Mirrors the frontend's active phase (api/run_lifecycle.ts::isActiveStatus).
_ACTIVE_STATUSES = frozenset({"queued", "running", "synthesizing"})


def _guard_deletable(run: RunRow) -> None:
    """Raise 403/409 when ``run`` cannot be permanently deleted yet.

    Raises:
        HTTPException: 403 for the shared demo run (a public fixture, not
            any one caller's data to remove); 409 when the run still has
            an active or resumable workflow, so a worker holding a lease
            never writes a child row for a run id that no longer exists.
    """
    if run.client_id == store.DEMO_CLIENT_ID:
        raise HTTPException(
            status_code=403, detail="the demo run cannot be deleted"
        )
    if run.status in _ACTIVE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="cancel the run before deleting it",
        )


@router.delete("/{run_id}")
async def delete_run(run_id: str) -> dict[str, Any]:
    """Permanently delete a run and every row scoped to it.

    The run must not be queued, running, or synthesizing -- an active run
    is cancelled first, through the existing cancel endpoint, so no worker
    holding its lease races the deletion. A draft, paused, or terminal run
    has nothing that could race and is always deletable. Deletion cascades
    through the run's hypotheses, evidence, reviews,
    citations, matches, safety decisions, reports, messages, checkpoints,
    metrics, and every other run-scoped table (enforced foreign keys, see
    ``app.store.runs``); it cannot be undone.

    Returns:
        The deleted run's id and the row counts removed, per table --
        proof the cascade reached everything, not just the run row.

    Raises:
        HTTPException: 404 if the run does not exist (or is not owned by
            the caller); 403 for the shared demo run; 409 if the run is
            still active.
    """
    run = _run_or_404(run_id)
    _guard_deletable(run)
    counts = store.delete_run(run_id)
    return {"id": run_id, "deleted": True, "counts": counts}


def _persist_new_run(  # noqa: PLR0913 -- retain the route module's patch seam.
    req: CreateRunRequest,
    request: Request,
    interview: dict[str, Any] | None,
    resolved: _ResolvedRunSettings,
    execution_policy: str = "standard",
    *,
    conn: sqlite3.Connection | None = None,
) -> store.RunRow:
    """Preserve the original helper signature and bind the same owner scope."""
    return _persist_new_run_for_owner(
        req,
        request,
        interview,
        resolved,
        execution_policy,
        owner=client_id(request),
        conn=conn,
    )


async def _generate_run_text(
    run_id: str,
    goal: str,
    byok: credentials.ByokCredential | None,
    execution_policy: str | None,
    *,
    restatement: bool = False,
) -> str | None:
    """Generate detached text under the run's policy and credential scope."""
    run: store.RunRow | None = None
    if execution_policy is None:
        run = store.get_run(run_id)
        if run is None:
            return None
        execution_policy = run.execution_policy
    elif execution_policy == CAMPAIGN:
        run = store.get_run(run_id)
    campaign_model = (
        campaign_model_for_config(run.config)
        if run is not None and execution_policy == CAMPAIGN
        else None
    )
    with (
        scoped_execution_policy(
            execution_policy, campaign_model_name=campaign_model
        ),
        credentials.scoped_byok(byok),
    ):
        generate = (
            generate_goal_restatement if restatement else generate_run_title
        )
        return await generate(goal)


async def _populate_run_title(
    run_id: str,
    goal: str,
    byok: credentials.ByokCredential | None = None,
    *,
    execution_policy: str | None = None,
) -> None:
    """Generate a run's short session title and persist it (best-effort).

    Runs after the create response as a background task, so the create call
    isn't blocked on a model round-trip. A None result (generation
    unavailable) leaves the title unset and surfaces fall back to a clause of
    the goal. A bring-your-own-key run titles under its own credential.

    Scheduled only for a run that has no title yet, so it never overwrites
    one the run's interview chose (see ``create_run``).

    Args:
        run_id: The run to title.
        goal: The run's research goal.
        byok: The run's credential, when it was created with one.
        execution_policy: Policy captured when the run was created.
    """
    title = await _generate_run_text(run_id, goal, byok, execution_policy)
    if title:
        store.set_run_title(run_id, title)


async def _populate_goal_restatement(
    run_id: str,
    goal: str,
    byok: credentials.ByokCredential | None = None,
    *,
    execution_policy: str | None = None,
) -> None:
    """Generate a run's narrative goal restatement and persist it.

    GOAL-RESTATEMENT-001. Runs after the create response as a background
    task, so create isn't blocked on a model round-trip. Best-effort: a None
    result leaves ``goal_restatement`` unset and the report omits the
    paragraph. A bring-your-own-key run restates under its own credential.

    Unlike titling, this is scheduled for every model-backed run regardless
    of whether the run's interview named it -- the restatement is a distinct
    report artifact, not the run's label.

    Args:
        run_id: The run to restate the goal of.
        goal: The run's research goal.
        byok: The run's credential, when it was created with one.
        execution_policy: Policy captured when the run was created.
    """
    restatement = await _generate_run_text(
        run_id, goal, byok, execution_policy, restatement=True
    )
    if restatement:
        store.set_run_goal_restatement(run_id, restatement)


def _apply_post_commit_effects(
    run: store.RunRow,
    req: CreateRunRequest,
    byok: Any,
    background_tasks: BackgroundTasks,
) -> None:
    """Run the effects that only make sense once the run row exists.

    They all need a persisted run id, so none can move ahead of the commit
    the way credential and document resolution do, and all need a real model
    -- offline/keyless runs keep the goal-clause title fallback and no
    restatement. Titling additionally skips a run its interview already
    named: the interview chose that name with the whole conversation in
    view, where generation sees only the goal, so regenerating would
    overwrite the better title with the worse. The restatement carries no
    such fallback, so it is scheduled for every model-backed run.

    Args:
        run: The freshly persisted run row.
        req: The create request, read for the research goal.
        byok: The caller's resolved bring-your-own-key credential, if any.
        background_tasks: Queue used to title the run and synthesize its
            goal restatement off the critical path.
    """
    model_backed = byok is not None or not engine_adapter.offline_mode()
    if run.title is None and model_backed:
        background_tasks.add_task(
            _populate_run_title,
            run.id,
            req.research_goal,
            byok,
            execution_policy=run.execution_policy,
        )
    # GOAL-RESTATEMENT-001: scheduled for every model-backed run (not gated on
    # the title, which the interview may already have supplied), off the
    # create critical path just like titling.
    if model_backed:
        background_tasks.add_task(
            _populate_goal_restatement,
            run.id,
            req.research_goal,
            byok,
            execution_policy=run.execution_policy,
        )


async def create_run(
    req: CreateRunRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Keep the registered endpoint and its patchable post-commit seam."""
    return await _create_run_with_callbacks(
        req,
        request,
        background_tasks,
        RunCreationCallbacks(
            require_client_scope=require_client_scope,
            client_id=client_id,
            resolve_execution_policy=resolve_execution_policy,
            scoped_execution_policy=scoped_execution_policy,
            resolve_byok=_resolve_byok,
            resolve_run_interview=_resolve_run_interview,
            resolve_run_settings=_resolve_run_settings,
            persist_new_run=_persist_new_run,
            run_setup_documents=_run_setup_documents,
            post_commit_effects=_apply_post_commit_effects,
        ),
    )


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
        awaiting = _awaiting_decision_count(run, conn=conn)
        failure_kind = None
        if run.status == RunStatus.FAILED.value:
            status_event = store.latest_status_event(run_id, conn=conn)
            if status_event and status_event.get("status") == run.status:
                failure_kind = status_event.get("failure_kind")
    return {
        **run.to_dict(),
        "failure_kind": failure_kind,
        "summary": summary,
        "execution_progress": progress,
        "awaiting_decision_count": awaiting,
    }


def _awaiting_decision_count(
    run: store.RunRow, *, conn: sqlite3.Connection
) -> int:
    """Count unresolved reviewable safety decisions blocking this run.

    Derived, not persisted: a run is "awaiting a person" exactly when it is
    paused *and* carries an unresolved ``requires_review`` decision -- both
    facts already live elsewhere (``runs.status``, ``safety_decisions``), so
    adding a third status value here would just let them disagree. Gated on
    ``paused`` first so every other run (the overwhelming majority) costs
    this endpoint nothing beyond the status check already in hand.
    """
    if run.status != RunStatus.PAUSED.value:
        return 0
    return store.count_unresolved_review_decisions(run.id, conn=conn)


async def rename_run(run_id: str, body: RenameRunRequest) -> dict[str, Any]:
    """Rename an owned run, replacing its existing session title.

    The title is only ever a label: it comes from the run's interview, or
    is generated from the goal after creation when the interview named
    nothing (see ``_populate_run_title``), and is read by the sidebar, the
    run titlebar and the report header -- nothing scientific derives from it.
    Renaming therefore has no run-state precondition -- an active run is
    renameable, and the new name is what its report carries when it lands.

    The research goal is deliberately not editable here. It is the input
    every hypothesis, review and tournament judgment was produced against,
    so rewriting it would leave a run whose record no longer states what it
    actually explored.

    Returns:
        The renamed run's details, in the same shape as ``get_run``.

    Raises:
        HTTPException: 404 if the run does not exist (or is not owned by
            the caller -- ``app.main.enforce_run_ownership`` answers that
            before this handler runs); 403 for a shared demo run, which
            that middleware deliberately exempts from ownership so every
            caller can read it, and which is therefore no one caller's to
            rename (the same guard ``app.runs.crud`` applies).
    """
    run = _run_or_404(run_id)
    if run.client_id == store.DEMO_CLIENT_ID:
        raise HTTPException(
            status_code=403, detail="the demo run cannot be renamed"
        )
    title = " ".join(body.title.split())
    if not title:
        raise HTTPException(status_code=422, detail="title cannot be blank")
    store.set_run_title(run_id, title)
    return await get_run(run_id)


__all__ = [
    "_ResolvedRunSettings",
    "_resolve_byok",
    "_resolve_run_interview",
    "_resolve_run_settings",
    "_run_setup_documents",
]
