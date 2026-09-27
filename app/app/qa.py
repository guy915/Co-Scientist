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
import re
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app import credentials, store
from app.config import settings
from app.execution_policy import scoped_execution_policy
from app.qa_manifest import QaRunContext as QaRunContext
from app.qa_manifest import build_evidence_manifest as build_evidence_manifest
from app.qa_manifest import build_system_prompt as build_system_prompt
from app.qa_stream import stream_llm_deltas as stream_llm_deltas
from app.sse import sse_frame as sse_frame

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class QaAnswerInputs:
    """Everything one streamed answer is grounded in.

    Bundled rather than passed one by one: the prompt, the manifest the
    answer cites against and the ideas its tool searches are three views of
    the same gathered context (see ``runs_chat._gather_qa_context``), and
    they are only ever assembled together.

    Attributes:
        system_prompt: The assembled grounding prompt.
        manifest: The numbered evidence manifest, emitted to the client
            first and stored with the answer.
        ideas: The run's ideas, which the ``search_ideas`` tool searches.
            Empty offers the model no tool, which is what a run with no
            ideas yet should do.
    """

    system_prompt: str
    manifest: list[dict[str, Any]]
    ideas: list[dict[str, Any]] = field(default_factory=list)


_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> frozenset[str]:
    """Split text into lowercase word tokens, dropping short noise words."""
    return frozenset(t for t in _WORD_RE.findall(text.lower()) if len(t) > 3)


def _question_ranked_hypotheses(
    question: str, hypotheses: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Reorder hypotheses so ones matching the question's terms lead.

    A hypothesis whose title shares vocabulary with the question is
    surfaced first, so the offline answer actually responds to what was
    asked rather than always reciting the top-Elo summary. When nothing
    matches (including an empty question), the stable sort's index
    tiebreak reproduces the input's own order -- the prior, question-blind
    behavior -- exactly.

    Returns:
        ``hypotheses`` reordered by (question-term overlap desc, original
        index asc).
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
    """Pick the review whose note best matches the question's terms.

    Ties -- including no review matching at all, or an empty question --
    fall back to the latest review, the prior unconditional behavior.

    Returns:
        The best-matching review, or None if there are no reviews.
    """
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
    question: str,
) -> str:
    """Compose a deterministic, grounded Q&A answer without a language model.

    Used for the keyless demo posture: instead of returning an API-key error,
    the run's own persisted artifacts (top hypotheses, the most relevant
    reviewer note, and the numbered evidence manifest) are synthesized into a
    plain grounded summary. The synthesis stays a deterministic function of
    the run state -- it never invents a claim the state does not contain --
    but the question's own vocabulary steers which hypotheses and review lead
    the answer, so it responds to what was asked instead of always reciting
    the same top-Elo summary regardless of the question.

    Returns:
        The grounded answer text.
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
    """Render the hypothesis-summary lines of the offline answer."""
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
    """Render the most relevant reviewer-note line, or nothing when absent."""
    if review is None:
        return []
    summary = (review.get("summary") or "").strip()
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
    deltas: AsyncIterator[tuple[str, str]],
) -> AsyncGenerator[str, None]:
    """Frame an answer's deltas as SSE and persist the assembled text.

    The single framing of a Q&A answer, shared by the model-backed and the
    offline paths so the workbench chat renders both identically: the cited
    sources first (so the UI can resolve ``[n]`` markers while the answer is
    still arriving), then one ``reasoning``/``chunk`` frame per delta (see
    ``qa_stream.stream_llm_deltas``), then ``done``. The persisted text and
    reasoning are the exact concatenation of the emitted frames of each
    kind, written before ``done`` so a reload right after completion shows
    the exchange -- reasoning included, matching what
    ``run_start_announcement.stream_announcement`` already does for the
    session card.

    Args:
        run_id: The run being asked about.
        question_id: Message id of the persisted question, echoed on ``done``.
        manifest: The evidence manifest, emitted first and stored with the
            answer.
        deltas: The answer's ``(kind, fragment)`` pairs, in the order they
            should stream.

    Yields:
        SSE ``data:`` frames.
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
    """Yield a pre-composed answer line by line, so the UI sees a stream.

    The offline answer is synthesized text, never a model's reasoning, so
    every line is a ``"chunk"``.
    """
    for line in answer.splitlines(keepends=True):
        yield "chunk", line


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


def _citation_meta(
    manifest: list[dict[str, Any]], reasoning: str
) -> dict[str, Any] | None:
    """Build the persisted-message meta dict carrying sources and reasoning.

    Mirrors ``run_start_announcement._persist_announcement``: either field
    rides in ``meta`` only when non-empty, so a reload shows exactly what
    the live turn showed, no more.
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
    """Persist the accumulated answer text, with its manifest and reasoning.

    Persisted before the caller signals `done`, so a reload right after
    completion still shows the exchange -- the chain of thought included.
    """
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


async def stream_answer(  # noqa: PLR0913
    run_id: str,
    question: QaQuestion,
    inputs: QaAnswerInputs,
    byok: credentials.ByokCredential | None = None,
    *,
    execution_policy: str | None = None,
    campaign_model_name: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream the LLM answer as SSE frames and persist the exchange.

    Emits the cited-source manifest first (so the UI can resolve ``[n]``
    references as the answer streams), then ``reasoning``/``chunk`` frames
    as the model writes them, then a ``done`` frame. On any error, persists
    and emits a fallback message. A bring-your-own-key credential is scoped
    around the whole stream so the answer is generated (and billed) on the
    run's own key.

    Args:
        run_id: The run being asked about.
        question: The scientist's question and its persisted message id.
        inputs: The prompt, evidence manifest and ideas the answer is
            grounded in.
        byok: Optional credential the answer is generated on.
        execution_policy: Policy captured when the run was authorized.
        campaign_model_name: Persisted model selected for campaign execution.

    Yields:
        SSE ``data:`` frames.
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
