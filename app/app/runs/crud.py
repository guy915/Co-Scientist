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
import app.store.receipts as run_creation_receipts
from app.auth import client_id, require_client_scope
from app.config import byok_enabled
from app.execution_policy import (
    CAMPAIGN,
    CAMPAIGN_MODEL_CONFIG_KEY,
    CAMPAIGN_MODEL_NAME,
    ZERO_COST_CONFIG_KEY,
    campaign_model_for_config,
    deployment_routes_are_free,
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
from app.store import (
    checkpoints,
    db,
    documents,
    events,
    interviews,
    records,
    tasks,
)
from app.store import runs as store
from app.store import runs_views as views
from app.store.models import DEMO_CLIENT_ID, RunRow, RunStatus
from app.store.runs import RunCreateOptions


def _reject_campaign_byok(
    credential: credentials.ByokCredential | None, execution_policy: str
) -> None:
    if credential is not None and execution_policy == CAMPAIGN:
        raise HTTPException(
            status_code=400,
            detail="campaign runs cannot use bring-your-own-key credentials",
        )


async def _resolve_byok(
    request: Request, execution_policy: str = "standard"
) -> credentials.ByokCredential | None:
    """Live credential validation happens before database writes, so
    rejected keys create no run and never hold the writer.
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
    if not req.interview_id:
        return None, req
    interview = interviews.get_interview(req.interview_id)
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
    """BYOK runs remain real-backed even under process-wide offline
    defaults; credentials never enter configuration.
    """
    provider = engine_adapter.select_provider()
    if byok is not None:
        llm_backend = "real"
    else:
        llm_backend = "offline" if engine_adapter.offline_mode() else "real"
    config, focus, tier = _build_run_config(req, interview)
    if byok is not None:
        # Persist only a provider flag, never a key; both backend resolution and
        # generator construction honor it.
        config["byok_provider"] = byok.provider
    return _ResolvedRunSettings(
        config=config,
        run_mode=tier,
        provider=provider,
        focus=focus,
        llm_backend=llm_backend,
    )


class _PersistNewRun(Protocol):
    def __call__(
        self,
        req: CreateRunRequest,
        request: Request,
        interview: dict[str, Any] | None,
        resolved: _ResolvedRunSettings,
        execution_policy: str = "standard",
        *,
        conn: sqlite3.Connection | None = None,
    ) -> RunRow: ...


@dataclass(frozen=True)
class RunCreationCallbacks:
    require_client_scope: Callable[[Request], str]
    client_id: Callable[[Request], str]
    resolve_execution_policy: Callable[[Request, dict[str, Any] | None], str]
    scoped_execution_policy: Callable[[str], AbstractContextManager[None]]
    resolve_byok: Callable[[Request, str], Awaitable[credentials.ByokCredential | None]]
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
            RunRow,
            CreateRunRequest,
            credentials.ByokCredential | None,
            BackgroundTasks,
        ],
        None,
    ]


def _receipt_replay(
    receipt: run_creation_receipts.RunCreationReceipt | None,
    request_digest: str,
) -> RunRow | None:
    if receipt is None:
        return None
    if receipt.request_digest != request_digest:
        raise HTTPException(409, "Idempotency-Key was used for another request")
    if receipt.run is None:
        raise HTTPException(404, "run not found")
    return receipt.run


def _persist_new_run_for_owner(
    req: CreateRunRequest,
    request: Request,
    interview: dict[str, Any] | None,
    resolved: _ResolvedRunSettings,
    execution_policy: str = "standard",
    *,
    owner: str,
    conn: sqlite3.Connection | None = None,
) -> RunRow:
    interview_title = None
    if interview:
        interview_title = clean_title(interview["fields"].get("title") or "")
    run = store.create_run(
        req.research_goal,
        resolved.run_mode,
        resolved.provider,
        resolved.config,
        RunCreateOptions(
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
        events.append_event(run.id, "lifecycle", event)
    else:
        events.append_event_deferred_log(run.id, "lifecycle", event, conn)
    return run


def _run_setup_documents(
    req: CreateRunRequest, interview: dict[str, Any] | None, owner: str
) -> list[dict[str, Any]]:
    named = staged_documents.resolve_owned_documents(req.document_ids, owner)
    return documents.merge_run_setup_documents(
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
    callbacks.require_client_scope(request)
    owner = callbacks.client_id(request)
    key = request.headers.get("Idempotency-Key")
    if key is not None and not (run_creation_receipts.valid_run_creation_key(key)):
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
                supervisor_api_key=request.headers.get(credentials.SUPERVISOR_API_KEY_HEADER),
                supervisor_provider=request.headers.get(credentials.SUPERVISOR_PROVIDER_HEADER),
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
        resolved_request = resolved_request.model_copy(update={"tier": free_usage.FREE_TIER})
        settings = callbacks.resolve_run_settings(resolved_request, interview, byok)
    if free:
        free_usage.check_request(resolved_request, settings.run_mode)
        if deployment_routes_are_free():
            settings = settings._replace(config={**settings.config, ZERO_COST_CONFIG_KEY: True})
    return _ResolvedSetup(resolved_request, interview, policy, byok, staged, settings, free)


def _persist_setup_transaction(
    admission: _Admission,
    setup: _ResolvedSetup,
    request: Request,
    callbacks: RunCreationCallbacks,
) -> tuple[
    RunRow | None,
    run_creation_receipts.RunCreationReceipt | None,
]:

    def persist_run(conn: sqlite3.Connection) -> RunRow:
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
        raise HTTPException(status_code=404, detail="attached document not found") from exc
    except free_usage.FreeUsageExhaustedError as exc:
        raise free_usage.exhausted_error() from exc
    return run, receipt


def _commit_setup(
    admission: _Admission,
    setup: _ResolvedSetup,
    request: Request,
    callbacks: RunCreationCallbacks,
) -> tuple[RunRow, bool]:
    run, receipt = _persist_setup_transaction(admission, setup, request, callbacks)
    if receipt is not None:
        replay = _receipt_replay(receipt, admission.request_digest or "")
        if replay is not None:
            return replay, False
    if run is None:
        raise RuntimeError("run creation returned no run or receipt")
    store.log_run_created(run)
    events.log_event_stage(
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
    admission = _admit_request(req, request, callbacks)
    if admission.replay is not None:
        return admission.replay
    setup = await _resolve_setup(req, request, admission.owner, callbacks)
    run, created = _commit_setup(admission, setup, request, callbacks)
    if created:
        callbacks.post_commit_effects(run, setup.request, setup.byok, background_tasks)
    return run.to_dict()


router = APIRouter()

# Live or claimable leases prevent deletion; parked and terminal runs have no
# writer to
# race.
_ACTIVE_STATUSES = frozenset({"queued", "running", "synthesizing"})


def _guard_deletable(run: RunRow) -> None:
    """Active or claimable leases prevent deletion, avoiding worker writes
    against a removed parent run.
    """
    if run.client_id == DEMO_CLIENT_ID:
        raise HTTPException(status_code=403, detail="the demo run cannot be deleted")
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


def _persist_new_run(
    req: CreateRunRequest,
    request: Request,
    interview: dict[str, Any] | None,
    resolved: _ResolvedRunSettings,
    execution_policy: str = "standard",
    *,
    conn: sqlite3.Connection | None = None,
) -> RunRow:
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
    run: RunRow | None = None
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
        scoped_execution_policy(execution_policy, campaign_model_name=campaign_model),
        credentials.scoped_byok(byok),
    ):
        generate = generate_goal_restatement if restatement else generate_run_title
        return await generate(goal)


async def _populate_run_title(
    run_id: str,
    goal: str,
    byok: credentials.ByokCredential | None = None,
    *,
    execution_policy: str | None = None,
) -> None:
    """Background titling preserves interview-chosen titles and leaves goal-
    clause fallback available when generation fails.
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
    """Goal restatement is a distinct report artifact, independent of
    whether the interview supplied a title.
    """
    restatement = await _generate_run_text(run_id, goal, byok, execution_policy, restatement=True)
    if restatement:
        store.set_run_goal_restatement(run_id, restatement)


def _apply_post_commit_effects(
    run: RunRow,
    req: CreateRunRequest,
    byok: Any,
    background_tasks: BackgroundTasks,
) -> None:
    """Detached generation needs a committed run ID and must preserve the
    better-informed interview title.
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


def _runs_payload(runs: list[RunRow]) -> dict[str, Any]:
    # Share one connection across list progress queries rather than opening one
    # per row.
    with db.connect() as conn:
        return {
            "runs": [
                {
                    **r.to_dict(),
                    "execution_progress": tasks.task_progress(r.id, conn=conn),
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
    runs = views.list_runs(client_id=subject, limit=limit)
    return _runs_payload(runs)


# Literal demo paths precede /{run_id} for first-match routing.
async def list_demo_runs() -> dict[str, Any]:
    """List the seeded demo runs, which are visible to every client."""
    runs = views.list_runs(client_id=DEMO_CLIENT_ID)
    return _runs_payload(runs)


async def get_run(run_id: str) -> dict[str, Any]:
    """Return a run's details plus per-table summary counts."""
    with db.connect() as conn:
        run = _run_or_404(run_id, conn=conn)
        summary = store.summary_counts(run_id, conn=conn)
        checkpoint = checkpoints.get_latest_checkpoint(run_id, conn=conn)
        if checkpoint and run.status in {
            RunStatus.QUEUED.value,
            RunStatus.RUNNING.value,
            RunStatus.SYNTHESIZING.value,
        }:
            envelope = checkpoint.get("state") or {}
            live_state = envelope.get("state") or {}
            # Checkpoint pools are committed scientific effects before final
            # publication
            # drains them into SQL tables.
            summary["hypotheses"] = max(
                summary["hypotheses"], len(live_state.get("hypotheses") or [])
            )
            summary["evidence"] = max(summary["evidence"], len(live_state.get("articles") or []))
        progress = tasks.task_progress(run_id, conn=conn)
        awaiting = _awaiting_decision_count(run, conn=conn)
        failure_kind = None
        if run.status == RunStatus.FAILED.value:
            status_event = events.latest_status_event(run_id, conn=conn)
            if status_event and status_event.get("status") == run.status:
                failure_kind = status_event.get("failure_kind")
    return {
        **run.to_dict(),
        "failure_kind": failure_kind,
        "summary": summary,
        "execution_progress": progress,
        "awaiting_decision_count": awaiting,
    }


def _awaiting_decision_count(run: RunRow, *, conn: sqlite3.Connection) -> int:
    """Awaiting review derives from paused status plus unresolved decisions,
    avoiding a third state that can drift.
    """
    if run.status != RunStatus.PAUSED.value:
        return 0
    return records.count_unresolved_review_decisions(run.id, conn=conn)


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
    if run.client_id == DEMO_CLIENT_ID:
        raise HTTPException(status_code=403, detail="the demo run cannot be renamed")
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
