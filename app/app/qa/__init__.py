from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import app.credentials as credentials
import app.offline_guard as offline_guard
import app.qa.manifest as qa_ideas
import app.store as store
from app.config import (
    CONVERSATIONAL_REASONING_EFFORT,
    THINKING_FLOOR_TIMEOUT_SECONDS,
    deepseek_thinking_kwargs,
    settings,
    thinking_safe_max_tokens,
)
from app.execution_policy import scoped_execution_policy
from app.llm_scope import budgeted_stream, stream_chunks
from app.qa.manifest import QaRunContext as QaRunContext
from app.qa.manifest import _tokenize
from app.qa.manifest import build_evidence_manifest as build_evidence_manifest
from app.qa.manifest import build_system_prompt as build_system_prompt
from app.sse import sse_frame as sse_frame

logger = logging.getLogger(__name__)

# Fund reasoning from separate headroom rather than the short answer budget.
_ANSWER_MAX_TOKENS = 4_000
# Bound provider silence, not total streaming duration, so thorough answers
# remain possible.
_QA_STALL_SECONDS = 45.0
_QA_TOTAL_SECONDS = THINKING_FLOOR_TIMEOUT_SECONDS + 60.0


def _completion_request(
    model: str,
    api_key: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Both rounds need the same reasoning headroom and deadline; tool results
    must not consume those protections.
    """
    request: dict[str, Any] = {
        "model": model,
        "messages": messages,
        # Without an explicit budget, thinking can exhaust the provider default
        # and return a clean but empty stream.
        "max_tokens": thinking_safe_max_tokens(model, _ANSWER_MAX_TOKENS),
        "timeout": _QA_TOTAL_SECONDS,
        "stream": True,
        "api_key": api_key,
        **deepseek_thinking_kwargs(
            model, effort=CONVERSATIONAL_REASONING_EFFORT
        ),
    }
    if tools:
        request["tools"] = tools
    return request


async def _stream_completion(
    request: dict[str, Any],
    tool_calls: dict[int, dict[str, Any]],
) -> AsyncGenerator[tuple[str, str], None]:
    import app.llm_request as llm_request

    response = await llm_request.acompletion(**request)
    async for chunk in stream_chunks(
        response,
        stall_seconds=_QA_STALL_SECONDS,
        total_seconds=_QA_TOTAL_SECONDS,
    ):
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta is None:
            continue
        qa_ideas.accumulate_tool_calls(tool_calls, delta)
        reasoning = getattr(delta, "reasoning_content", None) or ""
        if reasoning:
            yield "reasoning", str(reasoning)
        text = getattr(delta, "content", None) or ""
        if text:
            yield "chunk", str(text)


def _resolved_calls(
    tool_calls: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Providers may leave nameless fragments or omit call ids; a tool result
    still must identify its requesting call.
    """
    resolved = []
    for index, call in sorted(tool_calls.items()):
        if not call.get("name"):
            continue
        resolved.append({**call, "id": call.get("id") or f"call_{index}"})
    return resolved


def _tool_result_messages(
    calls: list[dict[str, Any]], ideas: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        {
            "role": "tool",
            "tool_call_id": call["id"],
            "name": call["name"],
            "content": qa_ideas.run_tool_call(call, ideas),
        }
        for call in calls
    ]


@budgeted_stream("qa")
async def stream_llm_deltas(
    model: str,
    system_prompt: str,
    question: str,
    ideas: list[dict[str, Any]],
) -> AsyncGenerator[tuple[str, str], None]:
    """Allow one lookup round only before prose starts; reasoning alone does not
    close that round. Starting a second answer after emitted prose would
    splice replies together.
    """
    # Enforce offline isolation at the request seam so future callers inherit
    # it.
    offline_guard.require_remote_chat("Q&A")
    # Scoped BYOK overrides both deployment model and credential.
    model, api_key = credentials.byok_model_and_key(model)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    tools = [qa_ideas.tool_declaration()] if ideas else None
    tool_calls: dict[int, dict[str, Any]] = {}
    answered = False
    async for kind, fragment in _stream_completion(
        _completion_request(model, api_key, messages, tools), tool_calls
    ):
        if kind == "chunk":
            answered = True
        yield kind, fragment
    calls = _resolved_calls(tool_calls)
    if answered or not calls:
        return
    messages += [
        qa_ideas.assistant_tool_message(calls),
        *_tool_result_messages(calls, ideas),
    ]
    async for kind, fragment in _stream_completion(
        _completion_request(model, api_key, messages, None), {}
    ):
        yield kind, fragment


@dataclass(frozen=True)
class QaQuestion:
    text: str
    message_id: int


@dataclass(frozen=True)
class QaAnswerInputs:
    """Prompt, citation manifest and searched ideas are views of the same
    gathered context.
    """

    system_prompt: str
    manifest: list[dict[str, Any]]
    ideas: list[dict[str, Any]] = field(default_factory=list)


def _question_ranked_hypotheses(
    question: str, hypotheses: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """With no question match, stable tie-breaking preserves the original
    ranking.
    """
    q_tokens = _tokenize(question)
    if not q_tokens:
        return hypotheses
    scored = sorted(
        enumerate(hypotheses),
        key=lambda pair: (
            -len(q_tokens & _tokenize(pair[1].get("title") or "")),
            pair[0],
        ),
    )
    return [hyp for _, hyp in scored]


def _question_relevant_review(
    question: str, reviews: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """With no question match, preserve the latest-review fallback."""
    if not reviews:
        return None
    q_tokens = _tokenize(question)
    best_overlap, best_index = max(
        (len(q_tokens & _tokenize(r.get("summary") or "")), i)
        for i, r in enumerate(reviews)
    )
    return reviews[best_index] if best_overlap > 0 else reviews[-1]


def _offline_hypothesis_lines(
    hypotheses: list[dict[str, Any]], has_sources: bool
) -> list[str]:
    lines: list[str] = []
    for rank, hyp in enumerate(hypotheses[:5], start=1):
        title = hyp.get("title") or "Untitled hypothesis"
        elo = hyp.get("elo_rating")
        wins = hyp.get("win_count")
        record = f" (Elo {elo}, {wins} wins)" if elo is not None else ""
        citation = " [1]" if has_sources and rank == 1 else ""
        lines.append(f"{rank}. {title}{record}{citation}")
    return lines


def build_offline_answer(
    research_goal: str,
    hypotheses: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    manifest: list[dict[str, Any]],
    question: str,
) -> str:
    """Offline synthesis must remain deterministic and never invent claims
    absent from persisted state.
    """
    parts: list[str] = [
        "Answering from this run's own artifacts (offline mode, no "
        "language model configured)."
    ]
    stripped_question = question.strip()
    if stripped_question:
        parts.append(f'Question asked: "{stripped_question}"')
    parts.append(f"Research goal: {research_goal}")
    ranked = _question_ranked_hypotheses(question, hypotheses)
    parts.extend(
        _offline_hypothesis_summary(ranked, manifest, ranked != hypotheses)
    )
    parts.extend(
        _offline_review_note(_question_relevant_review(question, reviews))
    )
    parts.extend(_offline_manifest_note(manifest))
    return "\n".join(parts)


def _offline_hypothesis_summary(
    hypotheses: list[dict[str, Any]],
    manifest: list[dict[str, Any]],
    question_matched: bool,
) -> list[str]:
    if not hypotheses:
        return [
            "No hypotheses have been generated for this run yet, so there "
            "is nothing to summarize."
        ]
    lead = (
        "the following most closely match your question:"
        if question_matched
        else "the top-ranked by Elo are:"
    )
    lines = [f"The run produced {len(hypotheses)} hypotheses; {lead}"]
    lines.extend(_offline_hypothesis_lines(hypotheses, bool(manifest)))
    return lines


def _offline_review_note(review: dict[str, Any] | None) -> list[str]:
    if review is None:
        return []
    summary = (review.get("summary") or "").strip()
    return [f"Latest reviewer note: {summary}"] if summary else []


def _offline_manifest_note(manifest: list[dict[str, Any]]) -> list[str]:
    if not manifest:
        return []
    top = manifest[0]
    return [
        f"Grounded in {len(manifest)} source(s), including "
        f"[1] {top.get('title') or 'Untitled source'}."
    ]


async def _framed_answer(
    run_id: str,
    question_id: int,
    manifest: list[dict[str, Any]],
    deltas: AsyncIterator[tuple[str, str]],
) -> AsyncGenerator[str, None]:
    """Emit sources before prose so live citations resolve; persist the exact
    emitted transcript before done for immediate reloads.
    """
    if manifest:
        yield sse_frame({"type": "sources", "sources": manifest})
    full: list[str] = []
    reasoning: list[str] = []
    async for kind, fragment in deltas:
        (reasoning if kind == "reasoning" else full).append(fragment)
        yield sse_frame({"type": kind, "content": fragment})
    _persist_qa_answer(run_id, full, reasoning, manifest)
    yield sse_frame({"type": "done", "question_id": question_id})


async def _offline_deltas(answer: str) -> AsyncIterator[tuple[str, str]]:
    """Offline synthesized prose is not model reasoning."""
    for line in answer.splitlines(keepends=True):
        yield "chunk", line


async def stream_offline_answer(
    run_id: str,
    question_id: int,
    answer: str,
    manifest: list[dict[str, Any]],
) -> AsyncGenerator[str, None]:
    async for frame in _framed_answer(
        run_id, question_id, manifest, _offline_deltas(answer)
    ):
        yield frame


def _citation_meta(
    manifest: list[dict[str, Any]], reasoning: str
) -> dict[str, Any] | None:
    """Persist only nonempty sources/reasoning so reloads show exactly what the
    live turn showed.
    """
    meta: dict[str, Any] = {}
    if manifest:
        meta["sources"] = manifest
    if reasoning:
        meta["reasoning"] = reasoning
    return meta or None


def _persist_qa_answer(
    run_id: str,
    full: list[str],
    reasoning: list[str],
    manifest: list[dict[str, Any]],
) -> None:
    answer = "".join(full)
    store.append_message(
        store.NewMessage(
            run_id=run_id,
            sender="system",
            content=answer,
            kind="qa",
            meta=_citation_meta(manifest, "".join(reasoning).strip()),
        )
    )


def _handle_qa_stream_error(run_id: str, exc: Exception) -> str:
    """Persist the emitted fallback on stream failures so chat history matches
    what the user saw.
    """
    logger.error("Q&A stream error for run %s: %s", run_id, exc)
    fallback = (
        "Q&A requires a language model API key "
        "(set CHAT_MODEL_NAME or MODEL_NAME)."
    )
    store.append_message(
        store.NewMessage(
            run_id=run_id, sender="system", content=fallback, kind="qa"
        )
    )
    return fallback


async def stream_answer(
    run_id: str,
    question: QaQuestion,
    inputs: QaAnswerInputs,
    byok: credentials.ByokCredential | None = None,
    *,
    execution_policy: str | None = None,
    campaign_model_name: str | None = None,
) -> AsyncGenerator[str, None]:
    """Scope BYOK through the whole stream so generation and billing use the
    run's authorized credential.
    """
    if execution_policy is None:
        run = store.get_run(run_id)
        if run is None:
            yield sse_frame({"type": "error", "message": "run not found"})
            return
        execution_policy = run.execution_policy
    try:
        with (
            scoped_execution_policy(
                execution_policy, campaign_model_name=campaign_model_name
            ),
            credentials.scoped_byok(byok),
        ):
            deltas = stream_llm_deltas(
                settings.effective_chat_model,
                inputs.system_prompt,
                question.text,
                inputs.ideas,
            )
            async for frame in _framed_answer(
                run_id, question.message_id, inputs.manifest, deltas
            ):
                yield frame
    except Exception as exc:
        fallback = _handle_qa_stream_error(run_id, exc)
        yield sse_frame({"type": "error", "message": fallback})


__all__ = [
    "QaRunContext",
    "build_evidence_manifest",
    "build_system_prompt",
    "sse_frame",
    "stream_llm_deltas",
]
