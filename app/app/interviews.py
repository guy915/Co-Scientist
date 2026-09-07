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
    store,
)
from app.auth import client_id, require_client_scope
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
    ProseSink as ProseSink,
)
from app.interviews_model import (
    ReasoningSink as ReasoningSink,
)
from app.interviews_model import (
    TurnSinks as TurnSinks,
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
from app.interviews_question_repair import (
    repair_questions as repair_questions,
)
from app.interviews_questions import (
    normalized_questions as normalized_questions,
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
    """Return an owned interview or raise without leaking its existence.

    An empty subject (no ``X-Client-ID`` header) never matches, even an
    interview whose own ``client_id`` happens to be empty too -- the same
    "an identity-less caller owns nothing" rule ``create_interview``
    enforces at creation time and ``app.main._run_ownership_response``
    enforces for runs.
    """
    interview = store.get_interview(interview_id)
    subject = client_id(request)
    if not subject or interview is None or interview["client_id"] != subject:
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
    interview_id: str,
    on_reasoning: ReasoningSink | None = None,
    on_prose: ProseSink | None = None,
) -> dict[str, Any]:
    """Run one Agent turn and persist its derivation for later resume.

    The turn's chain of thought is persisted alongside its message: a chat
    is short, so its own thinking stays in the transcript the next turn is
    derived from, and a resumed chat shows the reasoning the scientist
    watched arrive rather than dropping it.

    Args:
        interview_id: The interview to advance.
        on_reasoning: Optional sink for live chain-of-thought fragments.
        on_prose: Optional sink for the answer's prose as it is written.

    Returns:
        The updated interview row.
    """
    interview = store.get_interview(interview_id)
    assert interview is not None
    sink, fragments = _reasoning_capture(on_reasoning)
    response, used_fallback = await _run_interview_turn(
        interview, sink, on_prose
    )
    turn = await _with_repaired_questions(
        _resolved_turn(response, used_fallback, "".join(fragments))
    )
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
        questions: The structured multiple-choice answers this turn offers
            the scientist, if any. Unlike the fields -- which carry the
            interview's whole state forward every turn -- a question
            belongs to the turn that asked it and is never inherited, so
            this reads only from *this* turn's block.
    """

    message: str
    fields: dict[str, Any]
    reasoning: str
    completed: bool
    fallback: bool
    questions: list[dict[str, Any]]


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
        questions=normalized_questions(response.get("questions")),
    )


async def _with_repaired_questions(turn: _ResolvedTurn) -> _ResolvedTurn:
    """Return ``turn`` with the clickable answers its question was missing.

    A turn that asks a question is supposed to carry that question's options
    (see ``app.interviews_prompts``); the block is last in the reply, so it
    is what a truncated turn loses, and a model that ignores the instruction
    loses it too. Either way the prose already asked correctly, so the
    question is read back out of it rather than the turn being retried --
    see ``app.interviews_question_repair``, which returns nothing for a turn
    whose prose asks nothing and never invents a question.

    Skipped for a completing turn, which asks nothing by contract, and for a
    fallback turn, whose script is deterministic and has no model behind it
    to ask.
    """
    if turn.questions or turn.completed or turn.fallback:
        return turn
    questions = await repair_questions(turn.message)
    if not questions:
        return turn
    logger.info("Recovered %d interview question(s) from prose", len(questions))
    return dataclasses.replace(turn, questions=questions)


def _persist_interview_turn(interview_id: str, turn: _ResolvedTurn) -> None:
    """Append the Agent's turn and update the interview's derived fields."""
    store.append_interview_turn(
        interview_id,
        store.NewInterviewTurn(
            "agent",
            turn.message,
            turn.reasoning,
            fallback=turn.fallback,
            questions=turn.questions,
        ),
    )
    store.update_interview(
        interview_id,
        turn.fields,
        None if turn.completed else turn.message,
        completed=turn.completed,
    )


async def _run_interview_turn(
    interview: dict[str, Any],
    on_reasoning: ReasoningSink | None,
    on_prose: ProseSink | None = None,
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
        response = await _call_interview_model(
            interview, on_reasoning, on_prose
        )
        return response, False
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

    Raises:
        HTTPException: 400 when the caller carries no identity at all (see
            ``app.auth.require_client_scope``) -- checked first, since an
            interview created under that scope would be invisible to its
            own creator.
    """
    owner = require_client_scope(request)
    byok = _request_byok(request)
    # Refused before the interview row exists, so a bad id leaves nothing.
    documents.resolve_owned_documents(body.document_ids, owner)
    interview = store.create_interview(owner, body.research_challenge)
    _attach_documents(str(interview["id"]), body.document_ids, request)
    return _interview_stream(str(interview["id"]), byok)


@router.get("")
async def list_interviews(request: Request) -> list[dict[str, Any]]:
    """List the caller's chats, newest first, without their transcripts.

    Scoped to the calling client exactly as ``_owned_interview`` is: a chat
    carries a scientist's unfinished research goal, so it is never listed
    across clients. An identity-less caller's list is always empty, same
    as ``list_runs``.
    """
    subject = client_id(request)
    return store.list_interviews(subject) if subject else []


@router.get("/{interview_id}")
async def get_interview(interview_id: str, request: Request) -> dict[str, Any]:
    """Resume an owned interview with its full transcript and progress.

    Carries ``run_id`` -- the run this chat started, when it started one.
    Reopening is the only place that needs it, and it needs it to know the
    plan is settled: without it the workbench re-staged the completing turn
    as an editable draft with Start research live, beside a card saying the
    run was already under way.
    """
    interview = _owned_interview(interview_id, request)
    interview["run_id"] = store.run_id_for_interview(
        interview_id, client_id(request)
    )
    return interview


@router.delete("/{interview_id}")
async def delete_interview(
    interview_id: str, request: Request
) -> dict[str, Any]:
    """Permanently delete an owned chat and its transcript.

    Unlike a run (see ``app.runs_deletion``) a chat has no worker that
    could be mid-write, so there is no active state to refuse: an
    interview is only ever advanced by a request the caller makes. A chat
    already carried into a run is still deletable, and deleting it leaves
    that run untouched -- the run holds its own copy of everything the
    interview contributed.

    Returns:
        The deleted chat's id and the row counts removed, per table.

    Raises:
        HTTPException: 404 if the chat does not exist or is not owned by
            the caller (the two are deliberately indistinguishable, see
            ``_owned_interview``).
    """
    _owned_interview(interview_id, request)
    counts = store.delete_interview(interview_id)
    return {"id": interview_id, "deleted": True, "counts": counts}


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
