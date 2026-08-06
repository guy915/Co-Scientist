"""Run chat and interaction endpoints.

Scientist steering messages (queued and drained between iterations) and the
grounded Q&A endpoint with its streamed LLM (or deterministic offline)
answer. Split from ``app.runs`` by concern, matching the sibling endpoint
modules (``runs_lifecycle``, ``runs_collections``, ``runs_contrib``); the
router here is included into ``runs.router`` and every name is re-exported
from ``app.runs``, which remains the stable import and monkeypatch surface.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app import (
    credentials,
    engine_adapter,
    engine_tasks,
    paper_corpus,
    qa,
    store,
)
from app.audience import audience_chat_context
from app.runs_models import AskRequest, SendMessageRequest
from app.runs_support import _require_run, _run_or_404

router = APIRouter()


@router.post("/{run_id}/messages")
async def send_message(run_id: str, req: SendMessageRequest) -> dict[str, Any]:
    """Queue scientist steering and continue a completed engine run."""
    _require_run(run_id)
    # Stored with applied=0; the workflow drains pending steering messages
    # between iterations (store.get_pending_steering) and marks them applied.
    msg = store.append_message(
        store.NewMessage(
            run_id=run_id, sender="user", content=req.content, kind="steering"
        )
    )
    continuation = engine_tasks.enqueue_scientist_continuation(run_id, msg.id)
    return {
        **msg.to_dict(),
        "status": "queued",
        "continuation_task_id": continuation.id if continuation else None,
    }


@router.get("/{run_id}/messages")
async def list_messages(run_id: str) -> dict[str, Any]:
    """Return all messages for a run in chronological order."""
    _require_run(run_id)
    msgs = store.list_messages(run_id)
    return {"messages": [m.to_dict() for m in msgs]}


def _gather_qa_context(run: store.RunRow) -> qa.QaRunContext:
    """Load a run's state and build its numbered evidence manifest for Q&A."""
    # All six reads target the same run; share one connection.
    with store.connect() as conn:
        hypotheses = store.list_hypotheses(run.id, conn=conn)
        reviews = store.list_reviews(run.id, conn=conn)
        matches = store.list_matches(run.id, conn=conn)
        # [:-1] drops the question just appended above from the history.
        history = store.list_messages(run.id, conn=conn)[:-1]
        evidence = store.list_evidence(run.id, conn=conn)
        citations = store.list_citations(run.id, conn=conn)
    return qa.QaRunContext(
        research_goal=run.research_goal,
        hypotheses=hypotheses,
        reviews=reviews,
        matches=matches,
        history=history,
        manifest=qa.build_evidence_manifest(evidence, citations),
    )


def _offline_qa_response(
    run_id: str,
    question_msg: store.MessageRow,
    context: qa.QaRunContext,
) -> StreamingResponse:
    """Synthesize and stream a deterministic offline-mode Q&A answer.

    Keyless/offline posture: with no configured provider there is no
    language model to call, so synthesize a deterministic answer grounded in
    the run's own artifacts rather than streaming an API-key error. The real
    LLM path is unchanged for a configured provider.
    """
    answer = qa.build_offline_answer(
        context.research_goal,
        context.hypotheses,
        context.reviews,
        context.manifest,
    )
    return StreamingResponse(
        qa.stream_offline_answer(
            run_id, question_msg.id, answer, context.manifest
        ),
        media_type="text/event-stream",
    )


def _request_byok(
    request: Request,
) -> credentials.ByokCredential | None:
    """Parse optional BYOK headers, raising 400 for a malformed pair.

    A header key is only consulted by endpoints whose run has no stored
    credential of its own; see ``_resolve_qa_byok``.
    """
    try:
        return credentials.credential_from_headers(request.headers)
    except credentials.ByokRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _resolve_qa_byok(
    run_id: str, request: Request
) -> credentials.ByokCredential | None:
    """Resolve the credential a Q&A answer runs under, if any.

    The run's own stored credential wins -- Q&A must keep working on the
    run's key across sessions; a header key only covers a run that has
    none stored.
    """
    byok = credentials.get_run_credential(run_id)
    return byok if byok is not None else _request_byok(request)


@router.post("/{run_id}/messages/ask")
async def ask_question(
    run_id: str, req: AskRequest, request: Request
) -> StreamingResponse:
    """Answer a question about the run using a fast LLM.

    The response is streamed back to the caller.
    """
    run = _run_or_404(run_id)

    # Persist the question first so history survives even if streaming fails.
    question_msg = store.append_message(
        store.NewMessage(
            run_id=run_id, sender="user", content=req.question, kind="qa"
        )
    )

    # Prompt assembly and streaming are delegated to qa.py; the endpoint
    # only gathers state and wires the SSE response.
    context = _gather_qa_context(run)
    byok = _resolve_qa_byok(run_id, request)

    if engine_adapter.offline_mode() and byok is None:
        return _offline_qa_response(run_id, question_msg, context)

    system_prompt = qa.build_system_prompt(
        context,
        audience_context=audience_chat_context(req.audience),
        corpus_catalog=paper_corpus.catalog_context(req.audience),
    )
    return StreamingResponse(
        qa.stream_answer(
            run_id,
            qa.QaQuestion(text=req.question, message_id=question_msg.id),
            system_prompt,
            context.manifest,
            byok=byok,
        ),
        media_type="text/event-stream",
    )
