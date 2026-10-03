"""Durable interview turn advancement, independent of its HTTP router."""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from fastapi import HTTPException, Request

import app.credentials as credentials
import app.interviews.model as model
import app.interviews.questions as question_repair
import app.staged_documents as staged_documents
import app.store as store
from app.auth import client_id
from app.execution_policy import CAMPAIGN, STANDARD
from app.interviews.model import (
    ProseSink,
    ReasoningSink,
    _essentials_ready,
    _normalized_fields,
    _ready,
)
from app.interviews.questions import normalized_questions
from app.llm_scope import budgeted

logger = logging.getLogger(__name__)


def owned_interview(interview_id: str, request: Request) -> dict[str, Any]:
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


def request_byok(
    request: Request, execution_policy: str = STANDARD
) -> credentials.ByokCredential | None:
    """Parse optional BYOK headers for an interview turn, 400 if malformed.

    Interviews predate any run, so their model calls can only ride a
    per-request header credential (nothing is stored server-side).
    """
    try:
        credential = credentials.credential_from_headers(request.headers)
    except credentials.ByokRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if execution_policy == CAMPAIGN and credential is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "campaign interviews cannot use bring-your-own-key credentials"
            ),
        )
    return credential


def _with_documents(interview: dict[str, Any]) -> dict[str, Any]:
    """Add the interview's attached-document summaries to its payload.

    Metadata only: the extracted text is the model's context, not something
    the transcript has to carry back to the browser on every turn.

    Args:
        interview: The interview row to annotate, modified in place.

    Returns:
        The same row, carrying a ``documents`` list.
    """
    attached = store.list_interview_documents(str(interview["id"]))
    interview["documents"] = [
        staged_documents.document_summary(d) for d in attached
    ]
    return interview


def _attach_documents(
    interview_id: str, document_ids: list[str], request: Request
) -> None:
    """Attach staged documents to an interview, refusing an unowned id.

    Args:
        interview_id: The chat the documents belong to.
        document_ids: Ids staged through ``/api/documents``.
        request: Incoming request, used to read the owning identity.

    Raises:
        HTTPException: 404 when an id is unknown or belongs to another
            client (see ``staged_documents.resolve_owned_documents``).
    """
    if not document_ids:
        return
    owner = client_id(request)
    staged_documents.resolve_owned_documents(document_ids, owner)
    store.attach_documents_to_interview(interview_id, document_ids, owner)


# Preserve the interview log namespace across the lifecycle extraction.


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


@budgeted("interview")
async def advance_turn(
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
    (see ``app.interviews.model``); the block is last in the reply, so it
    is what a truncated turn loses, and a model that ignores the instruction
    loses it too. Either way the prose already asked correctly, so the
    question is read back out of it rather than the turn being retried --
    see ``app.interviews.questions``, which returns nothing for a turn
    whose prose asks nothing and never invents a question.

    Skipped for a completing turn, which asks nothing by contract, and for a
    fallback turn, whose script is deterministic and has no model behind it
    to ask.
    """
    if turn.questions or turn.completed or turn.fallback:
        return turn
    questions = await question_repair.repair_questions(turn.message)
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
        response = await model._call_interview_model(
            interview, on_reasoning, on_prose
        )
        return response, False
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        return model._fallback_interview_response(interview), True


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
