"""Grounded Q&A over a run: evidence manifest, prompt assembly, streaming.

The run-lifecycle router (``runs.py``) owns HTTP concerns; this module owns the
Q&A domain logic it delegates to: building the numbered, citation-ranked
evidence manifest (using the four-state citation model in ``citations.py``),
assembling the system prompt from the run's hypotheses/reviews/matches, and
streaming the LLM answer while persisting the exchange.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Iterator
from typing import Any

from app import store
from app.citations import STATE_RANK
from app.config import settings

logger = logging.getLogger(__name__)


def sse_frame(event: dict[str, Any]) -> str:
    """Format an event dict as a Server-Sent Events data frame."""
    return f"data: {json.dumps(event)}\n\n"


def _eligible_citations(
    citations: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
) -> Iterator[tuple[str, str]]:
    """Yield ``(evidence_id, state)`` for citations pointing at known evidence.

    Citations with no evidence id, or pointing at evidence we do not have,
    are skipped.
    """
    for citation in citations:
        raw_eid = citation.get("evidence_id")
        if raw_eid is None:
            continue
        eid = str(raw_eid)
        if eid in by_id:
            yield eid, str(citation.get("state") or "")


def _record_citation(
    cited_order: list[str],
    cited_state: dict[str, str],
    eid: str,
    state: str,
) -> None:
    """Record ``eid``'s manifest position (once) and its strongest state.

    An item's position is fixed by its first citation; a later citation of
    the same item can only upgrade its recorded state (never move it),
    keeping manifest numbering stable across the citation list.
    """
    if eid not in cited_state:
        # First citation of this item fixes its manifest position.
        cited_order.append(eid)
        cited_state[eid] = state
    elif STATE_RANK.get(state, -1) > STATE_RANK.get(cited_state[eid], -1):
        # Cited again with a stronger state: upgrade the state only,
        # keeping the original position so numbering stays stable.
        cited_state[eid] = state


def _rank_cited_evidence(
    citations: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
) -> tuple[list[str], dict[str, str]]:
    """Resolve each cited evidence id's manifest position and best state.

    Args:
        citations: Citation rows for the run.
        by_id: Evidence rows for the run, keyed by string id.

    Returns:
        A ``(cited_order, cited_state)`` pair: the evidence ids in first-cited
        order, and the strongest citation state seen for each id.
    """
    cited_state: dict[str, str] = {}
    cited_order: list[str] = []
    for eid, state in _eligible_citations(citations, by_id):
        _record_citation(cited_order, cited_state, eid, state)
    return cited_order, cited_state


def _resolve_entry_state(row: dict[str, Any], entry_state: str | None) -> str:
    """Resolve a manifest entry's state, defaulting uncited rows.

    Args:
        row: The evidence row.
        entry_state: The strongest citation state seen for this row, or None
            when the row was never cited.

    Returns:
        The citation state, or one derived from the row's availability flag
        when it was never cited.
    """
    if entry_state is not None:
        return entry_state
    return "available" if row.get("available", True) else "unavailable"


def _build_manifest_entries(
    ordered_ids: list[str],
    by_id: dict[str, dict[str, Any]],
    cited_state: dict[str, str],
    cap: int,
) -> list[dict[str, Any]]:
    """Materialize the capped, 1-based manifest entries for ``ordered_ids``.

    Args:
        ordered_ids: Evidence ids, cited items first, in manifest order.
        by_id: Evidence rows for the run, keyed by string id.
        cited_state: Strongest citation state seen for each cited id.
        cap: Maximum number of sources to include.

    Returns:
        A list of ``{n, evidence_id, title, url, source, year, state}`` dicts.
    """
    manifest: list[dict[str, Any]] = []
    # 1-based numbering matches the [n] citation markers in the prompt.
    for n, eid in enumerate(ordered_ids[:cap], start=1):
        row = by_id[eid]
        manifest.append(
            {
                "n": n,
                "evidence_id": eid,
                "title": row.get("title") or "Untitled source",
                "url": row.get("url"),
                "source": row.get("source"),
                "year": row.get("year"),
                "state": _resolve_entry_state(row, cited_state.get(eid)),
            }
        )
    return manifest


def build_evidence_manifest(
    evidence: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    cap: int = 12,
) -> list[dict[str, Any]]:
    """Build a numbered, deterministic source list for grounded Q&A.

    Cited evidence comes first (in citation order, keeping the strongest state
    when an item is cited by several claims), then any remaining evidence, all
    capped to keep the prompt bounded. Each entry carries the fields the model
    needs to cite and the UI needs to render a reference chip.

    Args:
        evidence: Evidence rows for the run.
        citations: Citation rows for the run.
        cap: Maximum number of sources to include.

    Returns:
        A list of ``{n, evidence_id, title, url, source, year, state}`` dicts.
    """
    by_id: dict[str, dict[str, Any]] = {
        str(e["id"]): e for e in evidence if e.get("id") is not None
    }
    cited_order, cited_state = _rank_cited_evidence(citations, by_id)
    # Uncited evidence trails the cited items, in retrieval (dict) order.
    ordered_ids = cited_order + [eid for eid in by_id if eid not in cited_state]
    return _build_manifest_entries(ordered_ids, by_id, cited_state, cap)


def _format_manifest_for_prompt(manifest: list[dict[str, Any]]) -> str:
    """Render the manifest as numbered lines for the system prompt."""
    lines = []
    for entry in manifest:
        meta = ", ".join(
            str(part)
            for part in (entry.get("source"), entry.get("year"))
            if part
        )
        suffix = f" ({meta})" if meta else ""
        lines.append(
            f"[{entry['n']}] {entry['title']}{suffix} — {entry['state']}"
        )
    return "\n".join(lines)


def build_system_prompt(
    research_goal: str,
    hypotheses: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    history: list[Any],
    manifest: list[dict[str, Any]],
) -> str:
    """Assemble the grounded-Q&A system prompt from a run's current state.

    Args:
        research_goal: The run's research goal.
        hypotheses: Hypothesis rows, already ordered by Elo descending.
        reviews: Reviewer/meta-review rows.
        matches: Tournament match rows.
        history: Prior messages (MessageRow) excluding the current question.
        manifest: The numbered evidence manifest for citation grounding.

    Returns:
        The system prompt string.
    """
    evidence_lines = _format_manifest_for_prompt(manifest)
    # Each section is truncated (top 5 hypotheses, last 5 reviews, last 3
    # matches, last 10 messages) to keep the prompt bounded on long runs.
    # list_hypotheses already orders by Elo descending.
    top_hyps = hypotheses[:5]
    hyp_lines = "\n".join(
        f"- [{h['title']}] Elo {h['elo_rating']}, "
        f"{h['win_count']}W/{h['loss_count']}L"
        for h in top_hyps
    )
    review_lines = "\n".join(
        f"- {r['reviewer_agent']} on {r['hypothesis_id'][:8]}: "
        f"{r['summary'][:120]}"
        for r in reviews[-5:]
    )
    match_lines = "\n".join(
        f"- Winner {m['winner_id'][:8]} (Elo {m['winner_elo_after']}) — "
        f"{(m.get('rationale') or '')[:100]}"
        for m in matches[-3:]
    )
    conv_lines = "\n".join(
        f"{'User' if m.sender == 'user' else 'Assistant'}: {m.content}"
        for m in history[-10:]
    )

    return (
        f"You are a concise research assistant helping the user understand "
        f"an ongoing AI-driven hypothesis generation run.\n\n"
        f"Research goal: {research_goal}\n\n"
        f"Top hypotheses by Elo:\n{hyp_lines or '(none yet)'}\n\n"
        f"Recent reviews:\n{review_lines or '(none yet)'}\n\n"
        f"Recent tournament matches:\n{match_lines or '(none yet)'}\n\n"
        f"Evidence (cite supporting sources inline as [n] using ONLY this "
        f"numbered list; never invent a citation):\n"
        f"{evidence_lines or '(no evidence retrieved)'}\n\n"
        f"Conversation history:\n{conv_lines or '(none)'}\n\n"
        f"Answer ONLY from this run's hypotheses, reviews, matches, and "
        f"evidence above -- do not draw on outside knowledge. If the run's "
        f"artifacts do not contain the answer, say so plainly rather than "
        f"speculating. Do not repeat the question. When a statement is "
        f"supported by a listed source, cite it inline as [n]."
    )


def _offline_hypothesis_lines(
    hypotheses: list[dict[str, Any]], has_sources: bool
) -> list[str]:
    """Render the top hypotheses as numbered lines for the offline answer.

    Args:
        hypotheses: Hypothesis rows, already ordered by Elo descending.
        has_sources: Whether a non-empty evidence manifest accompanies the
            answer, in which case the leading hypotheses cite it as ``[n]``.

    Returns:
        One formatted line per included hypothesis (top five at most).
    """
    lines: list[str] = []
    for rank, hyp in enumerate(hypotheses[:5], start=1):
        title = hyp.get("title") or "Untitled hypothesis"
        elo = hyp.get("elo_rating")
        wins = hyp.get("win_count")
        record = f" (Elo {elo}, {wins} wins)" if elo is not None else ""
        # Attach a citation marker to the leading hypotheses when the run has
        # sources, so the UI resolves them against the manifest frame.
        citation = f" [{rank}]" if has_sources and rank <= 1 else ""
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

    Args:
        research_goal: The run's research goal.
        hypotheses: Hypothesis rows, already ordered by Elo descending.
        reviews: Reviewer/meta-review rows for the run.
        manifest: The numbered evidence manifest for citation grounding.

    Returns:
        The grounded answer text.
    """
    parts: list[str] = [
        "Answering from this run's own artifacts (offline mode, no "
        "language model configured).",
        f"Research goal: {research_goal}",
    ]
    if hypotheses:
        parts.append(
            f"The run produced {len(hypotheses)} hypotheses; the "
            f"top-ranked by Elo are:"
        )
        parts.extend(_offline_hypothesis_lines(hypotheses, bool(manifest)))
    else:
        parts.append(
            "No hypotheses have been generated for this run yet, so there "
            "is nothing to summarize."
        )
    if reviews:
        latest = reviews[-1]
        summary = (latest.get("summary") or "").strip()
        if summary:
            parts.append(f"Latest reviewer note: {summary}")
    if manifest:
        top = manifest[0]
        parts.append(
            f"Grounded in {len(manifest)} source(s), including "
            f"[1] {top.get('title') or 'Untitled source'}."
        )
    return "\n".join(parts)


async def stream_offline_answer(
    run_id: str,
    question_id: int,
    answer: str,
    manifest: list[dict[str, Any]],
) -> AsyncGenerator[str, None]:
    """Stream a deterministic offline answer as SSE frames and persist it.

    Mirrors ``stream_answer``'s framing (a leading ``sources`` frame, then
    answer chunks, then ``done``) so the workbench chat renders the offline
    answer identically to a model-generated one, and persists the exchange
    with its evidence manifest.

    Args:
        run_id: The run being asked about.
        question_id: Message id of the persisted question, echoed on ``done``.
        answer: The pre-composed grounded answer text.
        manifest: The evidence manifest, stored with the answer.

    Yields:
        SSE ``data:`` frames.
    """
    if manifest:
        yield sse_frame({"type": "sources", "sources": manifest})
    # Emit the answer line by line so the UI renders it as a stream; the
    # persisted text is the exact concatenation of the emitted chunks.
    full: list[str] = []
    for chunk in answer.splitlines(keepends=True):
        full.append(chunk)
        yield sse_frame({"type": "chunk", "content": chunk})
    _persist_qa_answer(run_id, full, manifest)
    yield sse_frame({"type": "done", "question_id": question_id})


async def _stream_llm_deltas(
    model: str,
    system_prompt: str,
    question: str,
) -> AsyncGenerator[str, None]:
    """Call litellm with streaming enabled and yield plain text deltas.

    Deferred import keeps module import cheap and lets the caller's except
    branch turn a missing/broken litellm into the Q&A fallback message.

    Args:
        model: The model name to complete with.
        system_prompt: The assembled grounding prompt.
        question: The user's question.

    Yields:
        Non-empty text deltas from the streaming completion.
    """
    import litellm

    response = await litellm.acompletion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        stream=True,
    )
    async for chunk in response:
        delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
        if delta:
            yield delta


def _citation_meta(manifest: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Build the persisted-message meta dict carrying sources, if any."""
    return {"sources": manifest} if manifest else None


async def _relay_answer_chunks(
    model: str,
    system_prompt: str,
    question: str,
    full: list[str],
) -> AsyncGenerator[str, None]:
    """Yield chunk SSE frames while accumulating deltas into ``full``.

    Args:
        model: The model name to complete with.
        system_prompt: The assembled grounding prompt.
        question: The user's question.
        full: Mutable accumulator the caller reads once streaming completes.

    Yields:
        SSE ``data:`` chunk frames.
    """
    async for delta in _stream_llm_deltas(model, system_prompt, question):
        full.append(delta)
        yield sse_frame({"type": "chunk", "content": delta})


def _persist_qa_answer(
    run_id: str, full: list[str], manifest: list[dict[str, Any]]
) -> None:
    """Persist the accumulated answer text, with its evidence manifest.

    Persisted before the caller signals `done`, so a reload right after
    completion still shows the exchange.
    """
    answer = "".join(full)
    store.append_message(
        run_id, "system", answer, "qa", meta=_citation_meta(manifest)
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
    store.append_message(run_id, "system", fallback, "qa")
    return fallback


async def stream_answer(
    run_id: str,
    question: str,
    question_id: int,
    system_prompt: str,
    manifest: list[dict[str, Any]],
) -> AsyncGenerator[str, None]:
    """Stream the LLM answer as SSE frames and persist the exchange.

    Emits the cited-source manifest first (so the UI can resolve ``[n]``
    references as the answer streams), then answer chunks, then a ``done``
    frame. On any error, persists and emits a fallback message.

    Args:
        run_id: The run being asked about.
        question: The user's question.
        question_id: Message id of the persisted question, echoed on ``done``.
        system_prompt: The assembled grounding prompt.
        manifest: The evidence manifest, stored with the answer.

    Yields:
        SSE ``data:`` frames.
    """
    model = settings.effective_chat_model
    try:
        # Sources frame goes out before any text so the UI can resolve [n]
        # citation markers while the answer is still streaming.
        if manifest:
            yield sse_frame({"type": "sources", "sources": manifest})

        # Relay each token delta as its own SSE frame, accumulating the
        # full text so the complete answer can be persisted at the end.
        full: list[str] = []
        async for frame in _relay_answer_chunks(
            model, system_prompt, question, full
        ):
            yield frame

        _persist_qa_answer(run_id, full, manifest)
        yield sse_frame({"type": "done", "question_id": question_id})
    except Exception as exc:
        fallback = _handle_qa_stream_error(run_id, exc)
        yield sse_frame({"type": "error", "message": fallback})
