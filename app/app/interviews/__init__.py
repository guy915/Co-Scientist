from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

import app.interviews.turns as support
import app.staged_documents as staged_documents
from app.api_contracts.interviews import ChatSummary, Interview
from app.auth import client_id, require_client_scope
from app.execution_policy import resolve_execution_policy
from app.interviews.model import (
    CreateInterviewRequest as CreateInterviewRequest,
)
from app.interviews.model import (
    InterviewFieldsRequest as InterviewFieldsRequest,
)
from app.interviews.model import InterviewTurnRequest
from app.interviews.model import ProseSink as ProseSink
from app.interviews.model import ReasoningSink as ReasoningSink
from app.interviews.model import _call_interview_model as _call_interview_model
from app.interviews.model import _clean_list as _clean_list
from app.interviews.model import _essentials_ready as _essentials_ready
from app.interviews.model import (
    _fallback_interview_response as _fallback_interview_response,
)
from app.interviews.model import _normalized_fields as _normalized_fields
from app.interviews.model import _ready as _ready
from app.interviews.questions import (
    normalized_questions as normalized_questions,
)
from app.interviews.questions import repair_questions as repair_questions
from app.interviews.stream import _interview_stream
from app.interviews.turns import _attach_documents as _attach_documents
from app.interviews.turns import (
    _interview_turn_completed as _interview_turn_completed,
)
from app.interviews.turns import (
    _persist_interview_turn as _persist_interview_turn,
)
from app.interviews.turns import _reasoning_capture as _reasoning_capture
from app.interviews.turns import _resolved_turn as _resolved_turn
from app.interviews.turns import _ResolvedTurn as _ResolvedTurn
from app.interviews.turns import _run_interview_turn as _run_interview_turn
from app.interviews.turns import _with_documents as _with_documents
from app.interviews.turns import (
    _with_repaired_questions as _with_repaired_questions,
)
from app.interviews.turns import advance_turn as advance_turn
from app.interviews.turns import owned_interview as _owned_interview
from app.interviews.turns import request_byok as _request_byok
from app.store import interviews as store
from app.store.interviews import NewInterviewTurn

_revision_router = APIRouter()


def _require_revisable_turn(
    interview: dict[str, Any], turn_id: int, role: str
) -> None:
    if interview["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="interview is cancelled")
    turn = next(
        (t for t in interview["turns"] if int(t["id"]) == turn_id), None
    )
    if turn is None:
        raise HTTPException(status_code=404, detail="turn not found")
    if turn["role"] != role:
        raise HTTPException(
            status_code=409, detail=f"turn is not a {role} turn"
        )


def _reset_derivation(interview_id: str) -> None:
    """Rewinding a transcript withdraws derived fields and rebaselines the
    surviving conversation.
    """
    interview = store.get_interview(interview_id)
    assert interview is not None
    opening = next((t for t in interview["turns"] if t["role"] == "user"), None)
    store.update_interview(
        interview_id,
        {
            "research_challenge": str(opening["content"]) if opening else "",
            "focus_area": [],
            "preferences": [],
            "lab_constraints": [],
            "title": None,
        },
        "Continue the interview.",
        completed=False,
    )


def _rewind_and_restream(
    interview_id: str,
    turn_id: int,
    request: Request,
    *,
    role: str,
    replacement: str | None = None,
) -> StreamingResponse:
    """Edit and retry share ownership, revisability, rewind and derivation
    boundaries.
    """
    interview = support.owned_interview(interview_id, request)
    byok = support.request_byok(request, str(interview["execution_policy"]))
    _require_revisable_turn(interview, turn_id, role)
    store.rewind_interview(interview_id, turn_id)
    if replacement is not None:
        store.append_interview_turn(
            interview_id, NewInterviewTurn("user", replacement)
        )
    _reset_derivation(interview_id)
    return _interview_stream(
        interview_id,
        byok,
        execution_policy=str(interview["execution_policy"]),
    )


@_revision_router.put("/{interview_id}/turns/{turn_id}")
async def edit_interview_turn(
    interview_id: str,
    turn_id: int,
    body: InterviewTurnRequest,
    request: Request,
) -> StreamingResponse:
    """Replace one scientist turn in place and re-answer from there.

    An edited prompt is a correction, not a new question: the turn is
    rewritten where it stands and the Agent answers it again, rather than the
    old wording staying in the transcript with the correction appended after
    it -- which is what makes the two readings of "what did I ask?" disagree.
    Everything the Agent said after it was derived from the old wording, so
    it goes with it.
    """
    return _rewind_and_restream(
        interview_id, turn_id, request, role="user", replacement=body.content
    )


@_revision_router.post("/{interview_id}/turns/{turn_id}/retry")
async def retry_interview_turn(
    interview_id: str, turn_id: int, request: Request
) -> StreamingResponse:
    """Discard one Agent turn and answer the same prompt again.

    Retry has to remove the answer it is replacing. Re-running the model
    with the rejected turn still in the transcript asks it to continue from
    the answer rather than to reconsider it.
    """
    return _rewind_and_restream(interview_id, turn_id, request, role="agent")


router = APIRouter(prefix="/api/interviews", tags=["interviews"])

_advance = advance_turn


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
    execution_policy = resolve_execution_policy(request)
    byok = _request_byok(request, execution_policy)
    # Reject invalid attachment IDs before creating a row, avoiding orphan
    # interviews.
    staged_documents.resolve_owned_documents(body.document_ids, owner)
    interview = store.create_interview(
        owner,
        body.research_challenge,
        execution_policy=execution_policy,
    )
    _attach_documents(str(interview["id"]), body.document_ids, request)
    return _interview_stream(
        str(interview["id"]), byok, execution_policy=execution_policy
    )


@router.get("", response_model=list[ChatSummary])
async def list_interviews(request: Request) -> list[dict[str, Any]]:
    """List the caller's chats, newest first, without their transcripts.

    Scoped to the calling client exactly as ``_owned_interview`` is: a chat
    carries a scientist's unfinished research goal, so it is never listed
    across clients. An identity-less caller's list is always empty, same
    as ``list_runs``.
    """
    subject = client_id(request)
    return store.list_interviews(subject) if subject else []


@router.get("/{interview_id}", response_model=Interview)
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

    Unlike a run (see ``app.runs.crud``) a chat has no worker that
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
    interview = _owned_interview(interview_id, request)
    byok = _request_byok(request, str(interview["execution_policy"]))
    if interview["status"] != "active":
        raise HTTPException(status_code=409, detail="interview is not active")
    _attach_documents(interview_id, body.document_ids, request)
    store.append_interview_turn(
        interview_id, NewInterviewTurn("user", body.content)
    )
    return _interview_stream(
        interview_id,
        byok,
        execution_policy=str(interview["execution_policy"]),
    )


router.include_router(_revision_router)


@router.put("/{interview_id}/fields", response_model=Interview)
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


__all__ = [
    "CreateInterviewRequest",
    "InterviewFieldsRequest",
    "InterviewTurnRequest",
    "ProseSink",
    "ReasoningSink",
    "_ResolvedTurn",
    "_attach_documents",
    "_call_interview_model",
    "_clean_list",
    "_essentials_ready",
    "_fallback_interview_response",
    "_interview_stream",
    "_interview_turn_completed",
    "_normalized_fields",
    "_persist_interview_turn",
    "_ready",
    "_reasoning_capture",
    "_resolved_turn",
    "_run_interview_turn",
    "_with_documents",
    "_with_repaired_questions",
    "advance_turn",
    "normalized_questions",
    "repair_questions",
]
