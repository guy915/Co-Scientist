"""Evidence-manifest and prompt assembly for grounded Q&A.

Split from ``app.qa`` to keep that module focused on streaming and the
offline answer path; ``app.qa`` re-exports these names so callers keep
importing from it. This module owns the pure (no I/O) half of the Q&A
domain logic: building the numbered, citation-ranked evidence manifest
(using the four-state citation model in ``app.citations``) and assembling
the system prompt from the run's hypotheses/reviews/matches.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import Any

from app.citations import STATE_RANK
from app.qa.run_state import (
    ReportFacts,
    RunProgress,
    render_idea_index,
    render_progress,
    render_report,
)

# States a Q&A answer must not treat as support: "unsupported" means the
# claim was checked against the source and the source did not back it, and
# "unavailable" means the source could not be resolved at all. Both are
# withheld from the manifest entirely rather than shown-but-labelled, so the
# model can never cite one as [n] -- there is no [n] to cite.
_UNCITABLE_STATES = frozenset({"unsupported", "unavailable"})

# Evidence rows carry a full abstract; only a bounded excerpt goes into the
# prompt so one long abstract cannot dominate the manifest's token budget.
_PASSAGE_MAX_CHARS = 600


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


def _passage(row: dict[str, Any]) -> str | None:
    """Return a bounded excerpt of the evidence's abstract, or None.

    This is the content a citation actually grounds against: without it the
    model is told to cite ``[n]`` sources it was never shown the substance
    of, which invites fabricating what they say.
    """
    abstract = (row.get("abstract") or "").strip()
    if not abstract:
        return None
    if len(abstract) <= _PASSAGE_MAX_CHARS:
        return abstract
    return abstract[:_PASSAGE_MAX_CHARS].rstrip() + "…"


def _withhold_uncitable(
    ordered_ids: list[str],
    by_id: dict[str, dict[str, Any]],
    cited_state: dict[str, str],
) -> list[str]:
    """Drop ids whose resolved state cannot ground an answer.

    Args:
        ordered_ids: Evidence ids, cited items first, in manifest order.
        by_id: Evidence rows for the run, keyed by string id.
        cited_state: Strongest citation state seen for each cited id.

    Returns:
        ``ordered_ids`` with every ``unsupported``/``unavailable`` id
        removed, order otherwise preserved.
    """
    return [
        eid
        for eid in ordered_ids
        if _resolve_entry_state(by_id[eid], cited_state.get(eid))
        not in _UNCITABLE_STATES
    ]


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
        A list of ``{n, evidence_id, title, url, source, year, state,
        passage}`` dicts.
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
                "passage": _passage(row),
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
    when an item is cited by several claims), then any remaining evidence.
    Sources classified ``unsupported`` or ``unavailable`` are withheld
    entirely -- they were checked against a claim and found not to back it,
    or could not be resolved at all, so nothing about them belongs in a
    grounded answer's context. What remains is capped to keep the prompt
    bounded. Each entry carries the fields the model needs to cite (title,
    a grounding passage) and the UI needs to render a reference chip.

    Args:
        evidence: Evidence rows for the run.
        citations: Citation rows for the run.
        cap: Maximum number of sources to include.

    Returns:
        A list of ``{n, evidence_id, title, url, source, year, state,
        passage}`` dicts.
    """
    by_id: dict[str, dict[str, Any]] = {
        str(e["id"]): e for e in evidence if e.get("id") is not None
    }
    cited_order, cited_state = _rank_cited_evidence(citations, by_id)
    # Uncited evidence trails the cited items, in retrieval (dict) order.
    ordered_ids = cited_order + [eid for eid in by_id if eid not in cited_state]
    usable_ids = _withhold_uncitable(ordered_ids, by_id, cited_state)
    return _build_manifest_entries(usable_ids, by_id, cited_state, cap)


def _format_manifest_for_prompt(manifest: list[dict[str, Any]]) -> str:
    """Render the manifest as numbered lines for the system prompt.

    A source's passage (when one was retrieved) is rendered as a quoted
    line under its heading, so a citation has actual text to ground
    against rather than only a title.
    """
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
        passage = entry.get("passage")
        if passage:
            lines.append(f'    "{passage}"')
    return "\n".join(lines)


@dataclasses.dataclass(frozen=True)
class QaRunContext:
    """One run's current state, as the grounded-Q&A prompt sees it.

    Attributes:
        research_goal: The run's research goal.
        hypotheses: The run's hypotheses, already ordered by Elo descending.
        reviews: The run's reviews, oldest-first.
        matches: The run's tournament matches, oldest-first.
        history: Prior chat messages, excluding the current question.
        manifest: The numbered evidence manifest citations resolve against.
        progress: The run's execution state -- how long it has been going,
            what step it is on, what it has produced. None only for a caller
            that did not gather it.
        report: The finished report's synthesis, once the run has produced
            one; None while it is still running.
    """

    research_goal: str
    hypotheses: list[dict[str, Any]]
    reviews: list[dict[str, Any]]
    matches: list[dict[str, Any]]
    history: list[Any]
    manifest: list[dict[str, Any]]
    progress: RunProgress | None = None
    report: ReportFacts | None = None


@dataclasses.dataclass(frozen=True)
class _PromptSections:
    """The rendered prompt sections, in the order the template lays them out."""

    ideas: str
    reviews: str
    matches: str
    evidence: str
    conversation: str


def _summarize_run_context(context: QaRunContext) -> _PromptSections:
    """Summarize hypotheses, reviews, matches, evidence, and history.

    Every section but the idea index is truncated (last 5 reviews, last 3
    matches, last 10 messages) to keep the prompt bounded on long runs. The
    index is not: it is titles only, and it is what tells the model which
    ideas it can look up (see ``render_idea_index``).

    Returns:
        The five rendered prompt sections.
    """
    return _PromptSections(
        ideas=render_idea_index(context.hypotheses),
        reviews="\n".join(
            f"- {r['reviewer_agent']} on {r['hypothesis_id'][:8]}: "
            f"{r['summary'][:120]}"
            for r in context.reviews[-5:]
        ),
        matches="\n".join(
            f"- Winner {m['winner_id'][:8]} (Elo {m['winner_elo_after']}) — "
            f"{(m.get('rationale') or '')[:100]}"
            for m in context.matches[-3:]
        ),
        evidence=_format_manifest_for_prompt(context.manifest),
        conversation="\n".join(
            f"{'User' if m.sender == 'user' else 'Assistant'}: {m.content}"
            for m in context.history[-10:]
        ),
    )


# What the answer may and may not do with the context above. Kept apart
# from the sections so the rules read as one paragraph rather than as the
# tail of the last artifact rendered.
_ANSWER_RULES = (
    "Claims about this run -- what the ideas say, how they were reviewed "
    "or ranked, how far the run has got, and what the evidence shows -- "
    "must come ONLY from the context above and from the search_ideas tool. "
    "The idea index lists titles, not what the ideas say: call search_ideas "
    "before answering anything about an idea's content. If the run's "
    "artifacts do not contain the answer, say so plainly rather than "
    "speculating. Inline citations refer only to the numbered evidence "
    "list. Do not repeat the question. When a statement is supported by a "
    "listed source, cite it inline as [n]."
)


def _state_sections(context: QaRunContext) -> list[str]:
    """Render the run's own state: how it is going, and what it concluded.

    The report section is present only once the run has produced one, so a
    running run's prompt never carries an empty "Final report" heading for
    the model to answer out of.
    """
    sections: list[str] = []
    if context.progress is not None:
        sections.append(f"Run status:\n{render_progress(context.progress)}")
    if context.report is not None:
        body = render_report(context.report)
        if body:
            sections.append(f"Final report:\n{body}")
    return sections


def _artifact_sections(sections: _PromptSections) -> list[str]:
    """Render the run's artifacts in the order the prompt lays them out."""
    return [
        "Ideas in this run (titles only -- call the search_ideas tool for "
        f"what any of them actually says):\n{sections.ideas or '(none yet)'}",
        f"Recent reviews:\n{sections.reviews or '(none yet)'}",
        f"Recent tournament matches:\n{sections.matches or '(none yet)'}",
        "Evidence (cite supporting sources inline as [n] using ONLY this "
        "numbered list; never invent a citation):\n"
        f"{sections.evidence or '(no evidence retrieved)'}",
        f"Conversation history:\n{sections.conversation or '(none)'}",
    ]


def build_system_prompt(context: QaRunContext) -> str:
    """Assemble the grounded-Q&A system prompt from a run's current state.

    Args:
        context: The run state the answer must stay grounded in.

    Returns:
        The system prompt string.
    """
    sections = _summarize_run_context(context)
    blocks = [
        "You are a concise research assistant helping the user understand "
        "an AI-driven hypothesis generation run.",
        f"Research goal: {context.research_goal}",
        *_state_sections(context),
        *_artifact_sections(sections),
        _ANSWER_RULES,
    ]
    return "\n\n".join(blocks)
