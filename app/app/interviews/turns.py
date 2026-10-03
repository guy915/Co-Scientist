"""Durable interview turn advancement, independent of its HTTP router.

The turn captures model fragments, resolves fields and completion, repairs
missing answer options, and persists the resulting Agent reply. Transport
and revision handlers call this lifecycle without importing the router.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from fastapi import HTTPException

from app import store
from app.interviews import model, question_repair
from app.interviews.model import ProseSink, ReasoningSink
from app.interviews.prompts import (
    _essentials_ready,
    _normalized_fields,
    _ready,
)
from app.interviews.questions import normalized_questions
from app.interviews.support import _with_documents
from app.llm_scope import budgeted

# Preserve the interview log namespace across the lifecycle extraction.
logger = logging.getLogger("app.interviews")


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
    (see ``app.interviews.prompts``); the block is last in the reply, so it
    is what a truncated turn loses, and a model that ignores the instruction
    loses it too. Either way the prose already asked correctly, so the
    question is read back out of it rather than the turn being retried --
    see ``app.interviews.question_repair``, which returns nothing for a turn
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
