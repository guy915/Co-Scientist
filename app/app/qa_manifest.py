"""Evidence-manifest and prompt assembly for grounded Q&A.

Split from ``app.qa`` to keep that module focused on streaming and the
offline answer path; ``app.qa`` re-exports these names so callers keep
importing from it. This module owns the pure (no I/O) half of the Q&A
domain logic: building the numbered, citation-ranked evidence manifest
(using the four-state citation model in ``citations.py``) and assembling
the system prompt from the run's hypotheses/reviews/matches.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.citations import STATE_RANK


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
    audience_context: str = "",
    corpus_catalog: str = "",
) -> str:
    """Assemble the grounded-Q&A system prompt from a run's current state.

    ``hypotheses`` is assumed already ordered by Elo descending, and
    ``history`` excludes the current question. ``audience_context`` and
    ``corpus_catalog`` are appended only when non-empty; see
    ``_append_audience_context`` and ``_append_corpus_catalog``.

    Returns:
        The system prompt string.
    """
    evidence_lines = _format_manifest_for_prompt(manifest)
    hyp_lines, review_lines, match_lines, conv_lines = _summarize_run_context(
        hypotheses, reviews, matches, history
    )
    prompt = _base_system_prompt(
        research_goal,
        hyp_lines,
        review_lines,
        match_lines,
        evidence_lines,
        conv_lines,
    )
    prompt = _append_audience_context(prompt, audience_context)
    prompt = _append_corpus_catalog(prompt, corpus_catalog)
    return prompt


def _summarize_run_context(
    hypotheses: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    history: list[Any],
) -> tuple[str, str, str, str]:
    """Summarize hypotheses, reviews, matches, and history for the prompt.

    Each section is truncated (top 5 hypotheses, last 5 reviews, last 3
    matches, last 10 messages) to keep the prompt bounded on long runs.
    ``hypotheses`` is assumed already ordered by Elo descending.

    Returns:
        A ``(hyp_lines, review_lines, match_lines, conv_lines)`` tuple.
    """
    hyp_lines = "\n".join(
        f"- [{h['title']}] Elo {h['elo_rating']}, "
        f"{h['win_count']}W/{h['loss_count']}L"
        for h in hypotheses[:5]
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
    return hyp_lines, review_lines, match_lines, conv_lines


def _base_system_prompt(
    research_goal: str,
    hyp_lines: str,
    review_lines: str,
    match_lines: str,
    evidence_lines: str,
    conv_lines: str,
) -> str:
    """Render the grounded-Q&A system prompt before audience/corpus appends."""
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
        f"Claims about this run -- what the hypotheses say, how they were "
        f"reviewed or ranked, and what the evidence shows -- must come ONLY "
        f"from the artifacts above. If the run's artifacts do not contain "
        f"the answer, say so plainly rather than speculating. Background "
        f"about the user's field and its methods may draw on the background "
        f"section below when one is present, but never cite it as [n]: "
        f"inline citations refer only to the numbered evidence list. Do not "
        f"repeat the question. When a statement is supported by a listed "
        f"source, cite it inline as [n]."
    )


def _append_audience_context(prompt: str, audience_context: str) -> str:
    """Append the user's field background, when present, last."""
    # Appended last so the grounding rule above governs how it may be used.
    if not audience_context.strip():
        return prompt
    return prompt + (
        f"\n\nBackground about the user's field:\n{audience_context.strip()}"
    )


def _append_corpus_catalog(prompt: str, corpus_catalog: str) -> str:
    """Append the audience's paper catalog, when present."""
    # The catalog is real published work, unlike the background, so anything
    # taken from it must be attributed -- but by paper title, since these are
    # not in the numbered manifest and [n] has to keep resolving to it.
    if not corpus_catalog.strip():
        return prompt
    return prompt + (
        f"\n\nThe user's own group's published papers (title and abstract "
        f"of each). Attribute anything you take from them by paper title, "
        f"never as [n]. They are the group's prior work, not results from "
        f"this run -- do not present them as findings this run produced. "
        f"If an abstract is not enough to answer, note that the full text "
        f"can be read:\n{corpus_catalog.strip()}"
    )
