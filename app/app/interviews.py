"""Model-driven, durable research-goal interview API.

This module owns the durable turn lifecycle and the HTTP surface. The
provider call and its deterministic fallback live in ``interviews_model``,
the request-shaping half (schema, prompts, field normalization) in
``interviews_prompts``, the SSE transport for one turn's advancement in
``interviews_stream``, the request bodies in ``interviews_models``, and
the rewind/retry revision endpoints in ``interviews_revision`` (mounted
via ``router.include_router`` so they keep their original paths); all
are re-exported here, so ``app.interviews`` remains the stable import
and monkeypatch surface.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app import (
    credentials,
    documents,
    interviews_revision,
    paper_corpus,
    store,
)
from app.auth import client_id, principal_for_request
from app.interviews_documents import (
    _attach_documents as _attach_documents,
)
from app.interviews_documents import (
    _with_documents as _with_documents,
)
from app.interviews_model import (
    _INTERVIEW_STALL_SECONDS as _INTERVIEW_STALL_SECONDS,
)
from app.interviews_model import (
    _INTERVIEW_TOTAL_SECONDS as _INTERVIEW_TOTAL_SECONDS,
)
from app.interviews_model import (
    ReasoningSink as ReasoningSink,
)
from app.interviews_model import (
    _call_interview_model as _call_interview_model,
)
from app.interviews_model import (
    _collect_stream_content as _collect_stream_content,
)
from app.interviews_model import (
    _fallback_interview_response as _fallback_interview_response,
)
from app.interviews_model import (
    _stream_interview_content as _stream_interview_content,
)
from app.interviews_models import (
    CreateInterviewRequest as CreateInterviewRequest,
)
from app.interviews_models import (
    InterviewFieldsRequest as InterviewFieldsRequest,
)
from app.interviews_models import (
    InterviewTurnRequest as InterviewTurnRequest,
)
from app.interviews_prompts import (
    _RESPONSE_SCHEMA as _RESPONSE_SCHEMA,
)
from app.interviews_prompts import (
    _SYSTEM_PROMPT as _SYSTEM_PROMPT,
)
from app.interviews_prompts import (
    _clean_list as _clean_list,
)
from app.interviews_prompts import (
    _essentials_ready as _essentials_ready,
)
from app.interviews_prompts import (
    _interview_request as _interview_request,
)
from app.interviews_prompts import (
    _normalized_fields as _normalized_fields,
)
from app.interviews_prompts import (
    _prompt as _prompt,
)
from app.interviews_prompts import (
    _ready as _ready,
)
from app.interviews_prompts import (
    _system_prompt as _system_prompt,
)
from app.interviews_revision import (
    _require_revisable_turn as _require_revisable_turn,
)
from app.interviews_revision import (
    _reset_derivation as _reset_derivation,
)
from app.interviews_revision import (
    _rewind_and_restream as _rewind_and_restream,
)
from app.interviews_revision import (
    edit_interview_turn as edit_interview_turn,
)
from app.interviews_revision import (
    retry_interview_turn as retry_interview_turn,
)
from app.interviews_stream import (
    _advance_stream as _advance_stream,
)
from app.interviews_stream import (
    _interview_stream as _interview_stream,
)
from app.interviews_stream import (
    _resolve_advance_task as _resolve_advance_task,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/interviews", tags=["interviews"])


def _owned_interview(interview_id: str, request: Request) -> dict[str, Any]:
    """Return an owned interview or raise without leaking its existence."""
    interview = store.get_interview(interview_id)
    if interview is None or interview["client_id"] != client_id(request):
        raise HTTPException(status_code=404, detail="interview not found")
    return _with_documents(interview)


def _reasoning_capture(
    on_reasoning: ReasoningSink | None,
) -> tuple[ReasoningSink, list[str]]:
    """Return a reasoning sink that records fragments while relaying them.

    Returns:
        A ``(sink, fragments)`` pair; ``fragments`` fills as the model
        reasons, so the caller can persist the turn's whole chain of
        thought once the turn resolves.
    """
    fragments: list[str] = []

    async def sink(fragment: str) -> None:
        fragments.append(fragment)
        if on_reasoning is not None:
            await on_reasoning(fragment)

    return sink, fragments


async def _advance(
    interview_id: str, on_reasoning: ReasoningSink | None = None
) -> dict[str, Any]:
    """Run one Agent turn and persist its derivation for later resume.

    The turn's chain of thought is persisted alongside its message: a chat
    is short, so its own thinking stays in the transcript the next turn is
    derived from, and a resumed chat shows the reasoning the scientist
    watched arrive rather than dropping it.

    Args:
        interview_id: The interview to advance.
        on_reasoning: Optional sink for live chain-of-thought fragments.

    Returns:
        The updated interview row.
    """
    interview = store.get_interview(interview_id)
    assert interview is not None
    sink, fragments = _reasoning_capture(on_reasoning)
    response, used_fallback = await _run_interview_turn(interview, sink)
    turn = _resolved_turn(response, used_fallback, "".join(fragments))
    _persist_interview_turn(interview_id, turn)
    updated = store.get_interview(interview_id)
    assert updated is not None
    # The streamed turn is the same payload the GET returns, attachments
    # included: a client that only ever sees streamed frames would
    # otherwise never learn what is attached to the chat it is holding.
    return _with_documents(updated)


@dataclasses.dataclass(frozen=True)
class _ResolvedTurn:
    """What one advanced turn resolved to, before it is persisted.

    Attributes:
        message: The Agent's message to the scientist.
        fields: The five structured fields as this turn derived them.
        reasoning: The turn's whole chain of thought, as relayed.
        completed: Whether this turn completes the interview.
        fallback: True when the deterministic recovery path authored this
            turn because no model could be reached (neither the deployment
            credential nor a scoped bring-your-own-key one answered it).
            Persisted per turn so the UI signals exactly which turns are
            scripted; see ``store.NewInterviewTurn.fallback``.
    """

    message: str
    fields: dict[str, Any]
    reasoning: str
    completed: bool
    fallback: bool


def _resolved_turn(
    response: dict[str, Any], used_fallback: bool, reasoning: str
) -> _ResolvedTurn:
    """Read one model response into the turn record to persist.

    Returns:
        The resolved turn.

    Raises:
        HTTPException: 502 when the Agent returned no message to show.
    """
    fields = _normalized_fields(response)
    message = str(response.get("assistant_message") or "").strip()
    if not message:
        raise HTTPException(
            status_code=502, detail="Interview Agent returned no message."
        )
    return _ResolvedTurn(
        message=message,
        fields=fields,
        reasoning=reasoning,
        completed=_interview_turn_completed(response, fields, used_fallback),
        fallback=used_fallback,
    )


def _persist_interview_turn(interview_id: str, turn: _ResolvedTurn) -> None:
    """Append the Agent's turn and update the interview's derived fields."""
    store.append_interview_turn(
        interview_id,
        store.NewInterviewTurn(
            "agent", turn.message, turn.reasoning, fallback=turn.fallback
        ),
    )
    store.update_interview(
        interview_id,
        turn.fields,
        None if turn.completed else turn.message,
        completed=turn.completed,
    )


async def _run_interview_turn(
    interview: dict[str, Any], on_reasoning: ReasoningSink | None
) -> tuple[dict[str, Any], bool]:
    """Call the interview model, falling back on a 503.

    The flag is resolved per turn -- a deployment credential and a scoped
    bring-your-own-key credential both count as "model reached" -- and is
    persisted on the turn itself, so a mid-session credential change marks
    only the turns it authors.

    Returns:
        A ``(response, used_fallback)`` pair.
    """
    try:
        return await _call_interview_model(interview, on_reasoning), False
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        return _fallback_interview_response(interview), True


def _interview_turn_completed(
    response: dict[str, Any], fields: dict[str, Any], used_fallback: bool
) -> bool:
    """Return whether this turn completes the interview."""
    if used_fallback:
        # The deterministic recovery path sequences its questions via _ready,
        # so let it collect a preferences answer before completing.
        return _ready(fields)
    # Trust the model's own completion signal once the essentials are
    # captured. Empty preferences is a valid "no constraints" terminal state
    # per the interview contract, so requiring it here would deadlock the
    # interview whenever the scientist has no additional constraints.
    return bool(response.get("completed")) and _essentials_ready(fields)


def _request_byok(
    request: Request,
) -> credentials.ByokCredential | None:
    """Parse optional BYOK headers for an interview turn, 400 if malformed.

    Interviews predate any run, so their model calls can only ride a
    per-request header credential (nothing is stored server-side).
    """
    try:
        return credentials.credential_from_headers(request.headers)
    except credentials.ByokRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("")
async def create_interview(
    body: CreateInterviewRequest, request: Request
) -> StreamingResponse:
    """Start a durable Agent interview and stream its opening turn.

    Any documents named in the body are attached before the opening turn is
    derived, so the Agent's first question is already scoped by them.
    """
    byok = _request_byok(request)
    # Refused before the interview row exists, so a bad id leaves nothing.
    documents.resolve_owned_documents(body.document_ids, client_id(request))
    # Same corpus-audience gate as run creation and Q&A (paper_corpus.py):
    # a claim the caller cannot back with a verified researcher session is
    # downgraded before it is persisted, since the stored value is what
    # later unlocks the catalog for every turn of this interview.
    principal = principal_for_request(request)
    interview = store.create_interview(
        client_id(request),
        body.research_challenge,
        audience=paper_corpus.verified_audience(
            body.audience, principal.method if principal else None
        ),
    )
    _attach_documents(str(interview["id"]), body.document_ids, request)
    return _interview_stream(str(interview["id"]), byok)


@router.get("")
async def list_interviews(request: Request) -> list[dict[str, Any]]:
    """List the caller's chats, newest first, without their transcripts.

    Scoped to the calling client exactly as ``_owned_interview`` is: a chat
    carries a scientist's unfinished research goal, so it is never listed
    across clients.
    """
    return store.list_interviews(client_id(request))


@router.get("/{interview_id}")
async def get_interview(interview_id: str, request: Request) -> dict[str, Any]:
    """Resume an owned interview with its full transcript and progress."""
    return _owned_interview(interview_id, request)


@router.post("/{interview_id}/turns")
async def add_interview_turn(
    interview_id: str, body: InterviewTurnRequest, request: Request
) -> StreamingResponse:
    """Append a scientist answer and stream the Agent's next turn."""
    byok = _request_byok(request)
    interview = _owned_interview(interview_id, request)
    if interview["status"] != "active":
        raise HTTPException(status_code=409, detail="interview is not active")
    _attach_documents(interview_id, body.document_ids, request)
    store.append_interview_turn(
        interview_id, store.NewInterviewTurn("user", body.content)
    )
    return _interview_stream(interview_id, byok)


# The rewind/retry revision endpoints (PUT .../turns/{turn_id} and POST
# .../turns/{turn_id}/retry) live in app.interviews_revision and are
# mounted here so they keep their original paths under this router's
# "/api/interviews" prefix.
router.include_router(interviews_revision.router)


@router.put("/{interview_id}/fields")
async def edit_interview_fields(
    interview_id: str, body: InterviewFieldsRequest, request: Request
) -> dict[str, Any]:
    """Persist scientist edits and finalize when required fields are ready."""
    _owned_interview(interview_id, request)
    fields = body.model_dump()
    fields["focus_area"] = _clean_list(fields["focus_area"])
    fields["preferences"] = _clean_list(fields["preferences"])
    fields["lab_constraints"] = _clean_list(fields["lab_constraints"])
    completed = _ready(fields)
    store.update_interview(
        interview_id,
        fields,
        None if completed else "Continue the interview.",
        completed=completed,
    )
    updated = store.get_interview(interview_id)
    assert updated is not None
    return updated
