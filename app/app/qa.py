"""Grounded Q&A over a run: evidence manifest, prompt assembly, streaming.

The run-lifecycle router (``runs.py``) owns HTTP concerns; this module owns the
Q&A domain logic it delegates to: building the numbered, citation-ranked
evidence manifest (using the four-state citation model in ``citations.py``),
assembling the system prompt from the run's hypotheses/reviews/matches, and
streaming the LLM answer while persisting the exchange. The manifest and
prompt-assembly half lives in ``app.qa_manifest`` and is re-exported here so
callers keep importing from this module, as is the shared SSE encoder
``sse_frame`` (now ``app.sse``).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from typing import Any

from app import credentials, offline_guard, store
from app.config import (
    THINKING_FLOOR_TIMEOUT_SECONDS,
    deepseek_thinking_kwargs,
    settings,
    thinking_safe_max_tokens,
)
from app.llm_stream import stream_chunks
from app.qa_manifest import QaRunContext as QaRunContext
from app.qa_manifest import build_evidence_manifest as build_evidence_manifest
from app.qa_manifest import build_system_prompt as build_system_prompt
from app.sse import sse_frame as sse_frame

logger = logging.getLogger(__name__)

# A grounded answer cites passages and stays short; the ceiling is here so
# the reasoning is funded from its own headroom rather than the answer's.
_ANSWER_MAX_TOKENS = 4_000
# The answer streams into the chat as it is written, so silence is the only
# thing that distinguishes a dead provider from a thorough one.
_QA_STALL_SECONDS = 45.0
_QA_TOTAL_SECONDS = THINKING_FLOOR_TIMEOUT_SECONDS + 60.0


@dataclass(frozen=True)
class QaQuestion:
    """The persisted question one streamed answer replies to.

    Groups the pair so ``stream_answer`` stays at the argument ceiling.

    Attributes:
        text: The scientist's question.
        message_id: Message id of the persisted question row, echoed on
            the answer's ``done`` frame and stored with the answer.
    """

    text: str
    message_id: int


def _offline_hypothesis_lines(
    hypotheses: list[dict[str, Any]], has_sources: bool
) -> list[str]:
    """Render the top hypotheses as numbered lines for the offline answer.

    Args:
        hypotheses: Hypothesis rows, already ordered by Elo descending.
        has_sources: Whether a non-empty evidence manifest accompanies the
            answer, in which case the leading hypothesis cites it as ``[1]``.

    Returns:
        One formatted line per included hypothesis (top five at most).
    """
    lines: list[str] = []
    for rank, hyp in enumerate(hypotheses[:5], start=1):
        title = hyp.get("title") or "Untitled hypothesis"
        elo = hyp.get("elo_rating")
        wins = hyp.get("win_count")
        record = f" (Elo {elo}, {wins} wins)" if elo is not None else ""
        # Attach a citation marker to the leading hypothesis when the run has
        # sources, so the UI resolves it against the manifest frame.
        citation = " [1]" if has_sources and rank == 1 else ""
        lines.append(f"{rank}. {title}{record}{citation}")
    return lines


def build_offline_answer(
    research_goal: str,
    hypotheses: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    manifest: list[dict[str, Any]],
) -> str:
    """Compose a deterministic, grounded Q&A answer without a language model.

    Used for the keyless demo posture: instead of returning an API-key error,
    the run's own persisted artifacts (top hypotheses by Elo, the latest
    reviewer note, and the numbered evidence manifest) are synthesized into a
    plain grounded summary. The synthesis is a function of the run state only;
    it deliberately does not interpret or key off the question text, so it
    never fabricates a question-specific claim.

    Returns:
        The grounded answer text.
    """
    parts: list[str] = [
        "Answering from this run's own artifacts (offline mode, no "
        "language model configured).",
        f"Research goal: {research_goal}",
    ]
    parts.extend(_offline_hypothesis_summary(hypotheses, manifest))
    parts.extend(_offline_review_note(reviews))
    parts.extend(_offline_manifest_note(manifest))
    return "\n".join(parts)


def _offline_hypothesis_summary(
    hypotheses: list[dict[str, Any]], manifest: list[dict[str, Any]]
) -> list[str]:
    """Render the hypothesis-summary lines of the offline answer."""
    if not hypotheses:
        return [
            "No hypotheses have been generated for this run yet, so there "
            "is nothing to summarize."
        ]
    lines = [
        f"The run produced {len(hypotheses)} hypotheses; the "
        f"top-ranked by Elo are:"
    ]
    lines.extend(_offline_hypothesis_lines(hypotheses, bool(manifest)))
    return lines


def _offline_review_note(reviews: list[dict[str, Any]]) -> list[str]:
    """Render the latest-reviewer-note line, or nothing when absent."""
    if not reviews:
        return []
    summary = (reviews[-1].get("summary") or "").strip()
    return [f"Latest reviewer note: {summary}"] if summary else []


def _offline_manifest_note(manifest: list[dict[str, Any]]) -> list[str]:
    """Render the grounding-source-count line, or nothing when empty."""
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
    deltas: AsyncIterator[str],
) -> AsyncGenerator[str, None]:
    """Frame an answer's deltas as SSE and persist the assembled text.

    The single framing of a Q&A answer, shared by the model-backed and the
    offline paths so the workbench chat renders both identically: the cited
    sources first (so the UI can resolve ``[n]`` markers while the answer is
    still arriving), then one ``chunk`` frame per delta, then ``done``. The
    persisted text is the exact concatenation of the emitted chunks, written
    before ``done`` so a reload right after completion shows the exchange.

    Args:
        run_id: The run being asked about.
        question_id: Message id of the persisted question, echoed on ``done``.
        manifest: The evidence manifest, emitted first and stored with the
            answer.
        deltas: The answer text, in the order it should stream.

    Yields:
        SSE ``data:`` frames.
    """
    if manifest:
        yield sse_frame({"type": "sources", "sources": manifest})
    full: list[str] = []
    async for delta in deltas:
        full.append(delta)
        yield sse_frame({"type": "chunk", "content": delta})
    _persist_qa_answer(run_id, full, manifest)
    yield sse_frame({"type": "done", "question_id": question_id})


async def _offline_deltas(answer: str) -> AsyncIterator[str]:
    """Yield a pre-composed answer line by line, so the UI sees a stream."""
    for line in answer.splitlines(keepends=True):
        yield line


async def stream_offline_answer(
    run_id: str,
    question_id: int,
    answer: str,
    manifest: list[dict[str, Any]],
) -> AsyncGenerator[str, None]:
    """Stream a deterministic offline answer as SSE frames and persist it.

    Args:
        run_id: The run being asked about.
        question_id: Message id of the persisted question, echoed on ``done``.
        answer: The pre-composed grounded answer text.
        manifest: The evidence manifest, stored with the answer.

    Yields:
        SSE ``data:`` frames.
    """
    async for frame in _framed_answer(
        run_id, question_id, manifest, _offline_deltas(answer)
    ):
        yield frame


async def _stream_llm_deltas(
    model: str,
    system_prompt: str,
    question: str,
) -> AsyncGenerator[str, None]:
    """Call litellm with streaming enabled and yield plain text deltas.

    Deferred import keeps module import cheap and lets the caller's except
    branch turn a missing/broken litellm into the Q&A fallback message.
    A scoped bring-your-own-key credential overrides both the model and
    the deployment credential for this call.

    Args:
        model: The model name to complete with.
        system_prompt: The assembled grounding prompt.
        question: The user's question.

    Yields:
        Non-empty text deltas from the streaming completion.
    """
    import litellm

    # The endpoint already routes an offline process to the deterministic
    # grounded answer, so this never fires from there. It is here so the
    # invariant belongs to the call that makes the request rather than to
    # one caller that remembers to check -- any later caller of
    # stream_answer inherits it.
    offline_guard.require_remote_chat("Q&A")
    model, api_key = credentials.byok_model_and_key(model)
    response = await litellm.acompletion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        # Sending no budget takes the provider's default, which thinking can
        # exhaust before the first answer delta -- the stream then ends
        # clean and empty and the scientist gets a blank reply, not an error.
        max_tokens=thinking_safe_max_tokens(model, _ANSWER_MAX_TOKENS),
        timeout=_QA_TOTAL_SECONDS,
        stream=True,
        **deepseek_thinking_kwargs(model),
        **({"api_key": api_key} if api_key else {}),
    )
    async for chunk in stream_chunks(
        response,
        stall_seconds=_QA_STALL_SECONDS,
        total_seconds=_QA_TOTAL_SECONDS,
    ):
        delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
        if delta:
            yield delta


def _citation_meta(manifest: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Build the persisted-message meta dict carrying sources, if any."""
    return {"sources": manifest} if manifest else None


def _persist_qa_answer(
    run_id: str, full: list[str], manifest: list[dict[str, Any]]
) -> None:
    """Persist the accumulated answer text, with its evidence manifest.

    Persisted before the caller signals `done`, so a reload right after
    completion still shows the exchange.
    """
    answer = "".join(full)
    store.append_message(
        store.NewMessage(
            run_id=run_id,
            sender="system",
            content=answer,
            kind="qa",
            meta=_citation_meta(manifest),
        )
    )


def _handle_qa_stream_error(run_id: str, exc: Exception) -> str:
    """Log a Q&A stream failure, persist a fallback message, and return it.

    Any failure (missing key, provider error, mid-stream drop) ends the
    stream with a persisted fallback so the chat history stays consistent
    with what the user saw.
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
    system_prompt: str,
    manifest: list[dict[str, Any]],
    byok: credentials.ByokCredential | None = None,
) -> AsyncGenerator[str, None]:
    """Stream the LLM answer as SSE frames and persist the exchange.

    Emits the cited-source manifest first (so the UI can resolve ``[n]``
    references as the answer streams), then answer chunks, then a ``done``
    frame. On any error, persists and emits a fallback message. A
    bring-your-own-key credential is scoped around the whole stream so the
    answer is generated (and billed) on the run's own key.

    Yields:
        SSE ``data:`` frames.
    """
    try:
        with credentials.scoped_byok(byok):
            deltas = _stream_llm_deltas(
                settings.effective_chat_model, system_prompt, question.text
            )
            async for frame in _framed_answer(
                run_id, question.message_id, manifest, deltas
            ):
                yield frame
    except Exception as exc:
        fallback = _handle_qa_stream_error(run_id, exc)
        yield sse_frame({"type": "error", "message": fallback})
