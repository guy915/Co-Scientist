"""Interview revision: rewinding a turn and re-answering from there.

Split out of ``app.interviews``, which mounts this router via
``router.include_router`` so the endpoints stay reachable at their
original ``/api/interviews/{id}/turns/{turn_id}`` paths. Editing a
scientist turn and retrying an Agent turn are the same operation --
ownership check, revisability check, discarding the tail, re-deriving
the four fields, and streaming the next turn -- differing only in
which role they target and whether a replacement prompt takes the
rewound turn's place, so ``_rewind_and_restream`` is the one path both
routes call.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app import store
from app.interviews_models import InterviewTurnRequest
from app.interviews_stream import (
    _interview_stream,
)

router = APIRouter()


def _require_revisable_turn(
    interview: dict[str, Any], turn_id: int, role: str
) -> None:
    """Check the turn a revision targets, or raise a 4xx explaining why not.

    Raises:
        HTTPException: 409 when the interview is closed to revision, 404 when
            the turn is not one of its own, 409 when it is not the kind of
            turn this revision applies to.
    """
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
    """Re-baseline the five fields after a rewind, and reopen the interview.

    The stored fields are the model's derivation from a transcript that no
    longer exists, so keeping them would feed the next turn exactly the
    conclusions the scientist just withdrew. They are cleared back to the
    opening challenge -- whatever the first surviving user turn says -- and
    the model re-derives the rest from what remains.
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
    """Rewind an owned interview to ``turn_id`` and answer again from there.

    The one revision path. Editing a scientist turn and retrying an Agent
    turn differ only in which role they may target and whether a replacement
    prompt takes the rewound turn's place; everything else -- ownership, the
    revisability check, discarding the tail, re-deriving the four fields, and
    streaming the next turn -- is the same, and has to stay the same.

    Args:
        interview_id: The interview being revised.
        turn_id: The turn the revision targets; it and everything after it
            are discarded.
        request: Incoming request, used to check ownership.
        role: The role the targeted turn must have.
        replacement: Scientist text to append in the rewound turn's place,
            or None to re-answer the surviving prompt unchanged.

    Returns:
        The SSE response streaming the re-derived turn.
    """
    from app.interviews import _owned_interview, _request_byok

    interview = _owned_interview(interview_id, request)
    byok = _request_byok(request, str(interview["execution_policy"]))
    _require_revisable_turn(interview, turn_id, role)
    store.rewind_interview(interview_id, turn_id)
    if replacement is not None:
        store.append_interview_turn(
            interview_id, store.NewInterviewTurn("user", replacement)
        )
    _reset_derivation(interview_id)
    return _interview_stream(interview_id, byok)


@router.put("/{interview_id}/turns/{turn_id}")
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


@router.post("/{interview_id}/turns/{turn_id}/retry")
async def retry_interview_turn(
    interview_id: str, turn_id: int, request: Request
) -> StreamingResponse:
    """Discard one Agent turn and answer the same prompt again.

    Retry has to remove the answer it is replacing. Re-running the model
    with the rejected turn still in the transcript asks it to continue from
    the answer rather than to reconsider it.
    """
    return _rewind_and_restream(interview_id, turn_id, request, role="agent")
