"""Resolving a create-run request into what gets persisted.

Everything between the request body and the DRAFT row: the
bring-your-own-key credential, the goal interview it may have come
from, and the config those produce. Split from ``runs_crud`` so that
module stays under the line ceiling; the names callers use are re-exported
there, which remains their import and monkeypatch surface.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from fastapi import HTTPException, Request

from app import credentials, engine_adapter, store
from app.auth import client_id
from app.config import byok_enabled
from app.execution_policy import CAMPAIGN
from app.runs_models import CreateRunRequest, _build_create_run_config


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
