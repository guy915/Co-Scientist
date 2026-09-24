"""Run-creation admission and persistence orchestration."""

from __future__ import annotations

import sqlite3
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import BackgroundTasks, HTTPException, Request

from app import credentials, documents, run_corpus, store
from app.runs_crud_resolve import _ResolvedRunSettings
from app.runs_models import CreateRunRequest
from app.store import receipts as run_creation_receipts
from app.title_gen import clean_title


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
    named = documents.resolve_owned_documents(req.document_ids, owner)
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
    return _ResolvedSetup(
        resolved_request, interview, policy, byok, staged, settings
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
        return callbacks.persist_new_run(
            setup.request,
            request,
            setup.interview,
            setup.settings,
            setup.execution_policy,
            conn=conn,
        )

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


async def create_run(
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
