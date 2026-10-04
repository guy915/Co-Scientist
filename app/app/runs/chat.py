from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

import app.qa.manifest as qa_run_state
from app import (
    credentials,
    engine_adapter,
    engine_tasks,
    qa,
    run_start_announcement,
    store,
)
from app.api_contracts import MessagesResponse
from app.api_contracts.runs import RunMessage
from app.execution_policy import CAMPAIGN, campaign_model_for_config
from app.runs.models import (
    AskRequest,
    SendMessageRequest,
    StartAnnouncementRequest,
)
from app.runs.support import _require_run, _run_or_404

router = APIRouter()


@router.post("/{run_id}/messages", response_model=RunMessage)
async def send_message(run_id: str, req: SendMessageRequest) -> dict[str, Any]:
    """Queue scientist steering and continue a completed engine run."""
    _require_run(run_id)
    # Steering acknowledgement shares the checkpoint transaction so a claimable
    # worker
    # cannot lose the message.
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


@router.get("/{run_id}/messages", response_model=MessagesResponse)
async def list_messages(run_id: str) -> dict[str, Any]:
    """Return all messages for a run in chronological order."""
    _require_run(run_id)
    msgs = store.list_messages(run_id)
    return {"messages": [m.to_dict() for m in msgs]}


def _gather_qa_context(run: store.RunRow) -> qa.QaRunContext:
    """Q&A reads must not acquire SQLite's single writer."""
    with store.connect() as conn:
        hypotheses = store.list_hypotheses(run.id, conn=conn)
        reviews = store.list_reviews(run.id, conn=conn)
        matches = store.list_matches(run.id, conn=conn)
        history = store.list_messages(run.id, conn=conn)[:-1]
        evidence = store.list_evidence(run.id, conn=conn)
        citations = store.list_citations(run.id, conn=conn)
        progress = qa_run_state.gather_run_progress(
            run,
            reviews,
            {
                "ideas": len(hypotheses),
                "evidence": len(evidence),
                "matches": len(matches),
            },
            conn,
            time.time(),
        )
    return qa.QaRunContext(
        research_goal=run.research_goal,
        hypotheses=hypotheses,
        reviews=reviews,
        matches=matches,
        history=history,
        manifest=qa.build_evidence_manifest(evidence, citations),
        progress=progress,
        report=(
            None
            if progress.is_running
            else qa_run_state.gather_report_facts(run.id)
        ),
    )


def _offline_qa_response(
    run_id: str,
    question_msg: store.MessageRow,
    context: qa.QaRunContext,
) -> StreamingResponse:
    answer = qa.build_offline_answer(
        context.research_goal,
        context.hypotheses,
        context.reviews,
        context.manifest,
        question_msg.content,
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
    try:
        return credentials.credential_from_headers(request.headers)
    except credentials.ByokRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _resolve_qa_byok(
    run: store.RunRow, request: Request
) -> credentials.ByokCredential | None:
    """Persisted run credentials take precedence so billing remains
    consistent across sessions.
    """
    byok = credentials.get_run_credential(run.id)
    credential = byok if byok is not None else _request_byok(request)
    if run.execution_policy == CAMPAIGN and credential is not None:
        raise HTTPException(
            status_code=400,
            detail="campaign runs cannot use bring-your-own-key credentials",
        )
    return credential


def _persist_question(run_id: str, content: str) -> store.MessageRow:
    """The question remains durable even if the response stream fails."""
    return store.append_message(
        store.NewMessage(
            run_id=run_id, sender="user", content=content, kind="qa"
        )
    )


def _live_qa_response(
    req: AskRequest,
    run: store.RunRow,
    question_msg: store.MessageRow,
    context: qa.QaRunContext,
    byok: credentials.ByokCredential | None,
) -> StreamingResponse:
    return StreamingResponse(
        qa.stream_answer(
            run.id,
            qa.QaQuestion(text=req.question, message_id=question_msg.id),
            qa.QaAnswerInputs(
                system_prompt=qa.build_system_prompt(context),
                manifest=context.manifest,
                ideas=context.hypotheses,
            ),
            byok=byok,
            execution_policy=run.execution_policy,
            campaign_model_name=(
                campaign_model_for_config(run.config)
                if run.execution_policy == CAMPAIGN
                else None
            ),
        ),
        media_type="text/event-stream",
    )


@router.post("/{run_id}/messages/ask")
async def ask_question(
    run_id: str, req: AskRequest, request: Request
) -> StreamingResponse:
    """Answer a question about the run using a fast LLM.

    The response is streamed back to the caller.
    """
    run = _run_or_404(run_id)
    byok = _resolve_qa_byok(run, request)
    question_msg = _persist_question(run_id, req.question)

    context = _gather_qa_context(run)
    if engine_adapter.offline_mode() and byok is None:
        return _offline_qa_response(run_id, question_msg, context)
    return _live_qa_response(req, run, question_msg, context, byok)


@router.post("/{run_id}/messages/started")
async def announce_start(
    run_id: str, req: StartAnnouncementRequest, request: Request
) -> StreamingResponse:
    """Answer the scientist's start request in the Agent's own words.

    The reply the chat shows above the session card. It is a turn, not a
    notice: the scientist's prompt is persisted first (so the exchange
    survives a reload whatever the reply does), then the announcement
    streams and is persisted in turn. A provider this call cannot reach
    ends in the deterministic announcement rather than an error -- the run
    has already started by the time this endpoint is reached, and nothing
    here can change that.
    """
    run = _run_or_404(run_id)
    byok = _resolve_qa_byok(run, request)
    prompt_msg = run_start_announcement.persist_prompt(run_id, req.prompt)
    return StreamingResponse(
        run_start_announcement.stream_announcement(run, prompt_msg.id, byok),
        media_type="text/event-stream",
    )
