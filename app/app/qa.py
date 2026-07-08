"""Grounded Q&A over a run: evidence manifest, prompt assembly, streaming.

The run-lifecycle router (``runs.py``) owns HTTP concerns; this module owns the
Q&A domain logic it delegates to: building the numbered, citation-ranked
evidence manifest (using the four-state citation model in ``citations.py``),
assembling the system prompt from the run's hypotheses/reviews/matches, and
streaming the LLM answer while persisting the exchange.
"""
# pylint: disable=inconsistent-quotes

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from app import store
from app.citations import STATE_RANK
from app.config import settings

logger = logging.getLogger(__name__)


def sse_frame(event: dict[str, Any]) -> str:
    """Format an event dict as a Server-Sent Events data frame."""
    return f"data: {json.dumps(event)}\n\n"


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
    cited_state: dict[str, str] = {}
    cited_order: list[str] = []
    for citation in citations:
        raw_eid = citation.get("evidence_id")
        if raw_eid is None:
            continue
        eid = str(raw_eid)
        if eid not in by_id:
            continue
        state = str(citation.get("state") or "")
        if eid not in cited_state:
            cited_order.append(eid)
            cited_state[eid] = state
        elif STATE_RANK.get(state, -1) > STATE_RANK.get(cited_state[eid], -1):
            cited_state[eid] = state
    ordered_ids = cited_order + [eid for eid in by_id if eid not in cited_state]
    manifest: list[dict[str, Any]] = []
    for n, eid in enumerate(ordered_ids[:cap], start=1):
        row = by_id[eid]
        entry_state = cited_state.get(eid)
        if entry_state is None:
            entry_state = ("available"
                           if row.get("available", True) else "unavailable")
        manifest.append({
            "n": n,
            "evidence_id": eid,
            "title": row.get("title") or "Untitled source",
            "url": row.get("url"),
            "source": row.get("source"),
            "year": row.get("year"),
            "state": entry_state,
        })
    return manifest


def _format_manifest_for_prompt(manifest: list[dict[str, Any]]) -> str:
    """Render the manifest as numbered lines for the system prompt."""
    lines = []
    for entry in manifest:
        meta = ", ".join(
            str(part)
            for part in (entry.get("source"), entry.get("year"))
            if part)
        suffix = f" ({meta})" if meta else ""
        lines.append(f"[{entry['n']}] {entry['title']}{suffix}"
                     f" — {entry['state']}")
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
    # list_hypotheses already orders by Elo descending.
    top_hyps = hypotheses[:5]
    hyp_lines = "\n".join(
        f"- [{h['title']}] Elo {h['elo_rating']}, {h['win_count']}W/{h['loss_count']}L"  # pylint: disable=line-too-long
        for h in top_hyps)
    review_lines = "\n".join(
        f"- {r['reviewer_agent']} on {r['hypothesis_id'][:8]}: {r['summary'][:120]}"  # pylint: disable=line-too-long
        for r in reviews[-5:])
    match_lines = "\n".join(
        f"- Winner {m['winner_id'][:8]} (Elo {m['winner_elo_after']}) — {(m.get('rationale') or '')[:100]}"  # pylint: disable=line-too-long
        for m in matches[-3:])
    conv_lines = "\n".join(
        f"{'User' if m.sender == 'user' else 'Assistant'}: {m.content}"
        for m in history[-10:])

    return (
        f"You are a concise research assistant helping the user understand an ongoing "  # pylint: disable=line-too-long
        f"AI-driven hypothesis generation run.\n\n"
        f"Research goal: {research_goal}\n\n"
        f"Top hypotheses by Elo:\n{hyp_lines or '(none yet)'}\n\n"
        f"Recent reviews:\n{review_lines or '(none yet)'}\n\n"
        f"Recent tournament matches:\n{match_lines or '(none yet)'}\n\n"
        f"Evidence (cite supporting sources inline as [n] using ONLY this "
        f"numbered list; never invent a citation):\n"
        f"{evidence_lines or '(no evidence retrieved)'}\n\n"
        f"Conversation history:\n{conv_lines or '(none)'}\n\n"
        f"Answer concisely and accurately. Do not repeat the question. When a "
        f"statement is supported by a listed source, cite it inline as [n].")


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
    model = settings.chat_model_name or settings.model_name
    try:
        import litellm  # pylint: disable=import-outside-toplevel

        if manifest:
            yield sse_frame({"type": "sources", "sources": manifest})

        full: list[str] = []
        response = await litellm.acompletion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": question
                },
            ],
            stream=True,
        )
        async for chunk in response:
            delta = (chunk.choices[0].delta.content or
                     "") if chunk.choices else ""
            if delta:
                full.append(delta)
                yield sse_frame({"type": "chunk", "content": delta})

        answer = "".join(full)
        store.append_message(run_id,
                             "system",
                             answer,
                             "qa",
                             meta={"sources": manifest} if manifest else None)
        yield sse_frame({"type": "done", "question_id": question_id})
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Q&A stream error for run %s: %s", run_id, exc)
        fallback = "Q&A requires a language model API key (set CHAT_MODEL_NAME or MODEL_NAME)."  # pylint: disable=line-too-long
        store.append_message(run_id, "system", fallback, "qa")
        yield sse_frame({"type": "error", "message": fallback})
