"""Model-driven, durable research-goal interview API.

This module owns the HTTP surface. Durable turn advancement lives in
``interviews.turns`` and shared request guards in ``interviews.support``;
the provider call lives in ``interviews.model``, request shaping in
``interviews.prompts``, SSE transport in ``interviews.stream``, and revision
endpoints in ``interviews.revision``. Existing import names are re-exported
here; tests patch collaborators in their defining modules.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app import staged_documents, store
from app.api_contracts.interviews import ChatSummary, Interview
from app.auth import client_id, require_client_scope
from app.execution_policy import resolve_execution_policy
from app.interviews import revision as interviews_revision
from app.interviews.documents import (
    _attach_documents as _attach_documents,
)
from app.interviews.documents import (
    _with_documents as _with_documents,
)
from app.interviews.model import (
    ProseSink as ProseSink,
)
from app.interviews.model import (
    ReasoningSink as ReasoningSink,
)
from app.interviews.model import (
    _call_interview_model as _call_interview_model,
)
from app.interviews.model import (
    _fallback_interview_response as _fallback_interview_response,
)
from app.interviews.models import (
    CreateInterviewRequest as CreateInterviewRequest,
)
from app.interviews.models import (
    InterviewFieldsRequest as InterviewFieldsRequest,
)
from app.interviews.models import (
    InterviewTurnRequest as InterviewTurnRequest,
)
from app.interviews.prompts import (
    _clean_list as _clean_list,
)
from app.interviews.prompts import (
    _essentials_ready as _essentials_ready,
)
from app.interviews.prompts import (
    _normalized_fields as _normalized_fields,
)
from app.interviews.prompts import (
    _ready as _ready,
)
from app.interviews.question_repair import (
    repair_questions as repair_questions,
)
from app.interviews.questions import (
    normalized_questions as normalized_questions,
)
from app.interviews.stream import (
    _interview_stream as _interview_stream,
)
from app.interviews.support import (
    owned_interview as _owned_interview,
)
from app.interviews.support import (
    request_byok as _request_byok,
)
from app.interviews.turns import (
    _interview_turn_completed as _interview_turn_completed,
)
from app.interviews.turns import (
    _persist_interview_turn as _persist_interview_turn,
)
from app.interviews.turns import (
    _reasoning_capture as _reasoning_capture,
)
from app.interviews.turns import (
    _resolved_turn as _resolved_turn,
)
from app.interviews.turns import (
    _ResolvedTurn as _ResolvedTurn,
)
from app.interviews.turns import (
    _run_interview_turn as _run_interview_turn,
)
from app.interviews.turns import (
    _with_repaired_questions as _with_repaired_questions,
)
from app.interviews.turns import (
    advance_turn as advance_turn,
)

router = APIRouter(prefix="/api/interviews", tags=["interviews"])

# Compatibility import path; durable advancement is owned by turns.
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
    # Refused before the interview row exists, so a bad id leaves nothing.
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

    Unlike a run (see ``app.runs.deletion``) a chat has no worker that
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
        interview_id, store.NewInterviewTurn("user", body.content)
    )
    return _interview_stream(
        interview_id,
        byok,
        execution_policy=str(interview["execution_policy"]),
    )


# The rewind/retry revision endpoints (PUT .../turns/{turn_id} and POST
# .../turns/{turn_id}/retry) live in app.interviews.revision and are
# mounted here so they keep their original paths under this router's
# "/api/interviews" prefix.
router.include_router(interviews_revision.router)


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
