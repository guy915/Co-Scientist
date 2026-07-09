"""Shared report-rendering, finalization, and event-payload helpers.

Homed here (rather than inside a single provider) so both the real-engine
drain (``engine_adapter``) and the deterministic mock (``mock_workflow``) build
the report payload, render its markdown, run the final safety gate, and emit the
report/completed events through one implementation -- keeping the persisted
report, the final-gate policy, and the streamed event shapes identical across
providers.
"""
# pylint: disable=inconsistent-quotes

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app import store
from app.elo import live_leaderboard
from app.safety import apply_safety_gate, screen_final
from app.store import RunStatus

# Emitter both providers pass in: records an event and returns its stub.
EmitFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def make_emitter(
    run_id: str,
    *,
    db_path: str | None = None,
    sleep_seconds: float = 0.0,
) -> EmitFn:
    """Build the per-run event emitter both providers stream through.

    Records an event via ``store.append_event`` and returns the streamed stub
    ``{"seq", "type", "payload"}`` -- the single home for that SSE contract
    shape. The mock passes ``sleep_seconds`` to pace its synthetic timeline; the
    engine leaves it at 0 (the generator's ``yield`` already cedes control).

    Args:
        run_id: Identifier of the run whose events are recorded.
        db_path: Optional override for the SQLite database path.
        sleep_seconds: Optional per-event pacing delay (mock only).

    Returns:
        An async emitter callable matching ``EmitFn``.
    """

    async def emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        # append_event assigns and returns the monotonic per-run sequence
        # number used by the SSE stream's replay-then-live protocol.
        seq = store.append_event(run_id, type_, payload, db_path=db_path)
        if sleep_seconds:
            await asyncio.sleep(sleep_seconds)
        return {"seq": seq, "type": type_, "payload": payload}

    return emit


def hypothesis_stub(h: dict[str, Any]) -> dict[str, str]:
    """Project a hypothesis to a minimal JSON-safe stub for event payloads."""
    return {
        "id": str(h.get("id") or h.get("hypothesis_id") or ""),
        "title": str(h.get("title") or h.get("text") or "Untitled")[:140],
    }


def article_stub(a: dict[str, Any]) -> dict[str, str]:
    """Project an article to a minimal JSON-safe stub for event payloads."""
    return {
        "title": str(a.get("title") or "Untitled"),
        "url": str(a.get("url") or ""),
    }


def match_stub(m: dict[str, Any]) -> dict[str, str]:
    """Project a tournament matchup to a minimal JSON-safe stub."""
    return {"winner": str(m.get("winner") or "")}


def _append_if(lines: list[str], label: str, value: str) -> None:
    """Append a ``  Label: value`` line to lines when value is non-empty."""
    if value:
        lines.append(f"  {label}: {value}")


def _render_probe(idx: int, probe: dict[str, Any]) -> list[str]:
    """Render one deep-verification probe entry."""
    fundamental = bool(probe.get("assumption_is_fundamental"))
    flag = "fundamental" if fundamental else "non-fundamental"
    lines = [f"Probe {idx} ({flag} assumption):"]
    for label, key in (
        ("Question", "question"),
        ("Answer", "answer"),
        ("Reasoning", "reasoning"),
    ):
        _append_if(lines, label, str(probe.get(key, "")).strip())
    lines.append("")
    return lines


def format_deep_verification_critique(
    probes: list[dict[str, Any]], verdict: str | None
) -> tuple[str, str]:
    """Render deep-verification probes into a (summary, critique) pair.

    Args:
        probes: Probing-question entries, each carrying ``question``,
            ``answer``, ``reasoning``, and ``assumption_is_fundamental``.
        verdict: Overall verdict, one of ``holds``/``weakened``/``undermined``,
            or None when the engine did not return one.

    Returns:
        A tuple of (summary, critique). Both are non-empty strings suitable
        for the NOT NULL reviews columns.
    """
    verdict_text = verdict or "unspecified"
    summary = f"Deep verification verdict: {verdict_text}"
    lines: list[str] = [summary, ""]
    for idx, probe in enumerate(probes, start=1):
        lines += _render_probe(idx, probe)
    critique = "\n".join(lines).strip()
    return summary, critique


def _render_optional_paragraph(text: str | None) -> list[str]:
    """Render a single trailing-blank-line paragraph, or nothing when empty."""
    return [f"{text}\n"] if text else []


def _render_experiments_list(experiments: list[Any]) -> list[str]:
    """Render the 'Suggested experiments' bullet list, or nothing when empty."""
    if not experiments:
        return []
    return (
        ["Suggested experiments:\n"]
        + [f"- {experiment}" for experiment in experiments]
        + [""]
    )


def _render_research_direction(direction: dict[str, Any]) -> list[str]:
    """Render one research-direction entry, or nothing when not a dict."""
    if not isinstance(direction, dict):
        return []
    lines = [f"### {direction.get('title', '')}\n"]
    lines += _render_optional_paragraph(direction.get("importance", ""))
    lines += _render_experiments_list(
        direction.get("suggested_experiments") or []
    )
    return lines


def _has_overview_content(summary: str | None, directions: list[Any]) -> bool:
    """Return whether the overview section has any renderable content."""
    return bool(summary or directions)


def _render_directions_list(directions: list[Any]) -> list[str]:
    """Render each research-direction entry in sequence."""
    lines: list[str] = []
    for direction in directions:
        lines += _render_research_direction(direction)
    return lines


def _render_overview_section(ov: dict[str, Any]) -> list[str]:
    """Render the 'Research Overview' section, or nothing when data absent."""
    if not isinstance(ov, dict):
        return []
    summary = ov.get("summary")
    directions = ov.get("research_directions") or []
    if not _has_overview_content(summary, directions):
        return []
    lines = ["\n## Research Overview\n"]
    lines += _render_optional_paragraph(summary)
    return lines + _render_directions_list(directions)


def _render_nih_aim(aim: dict[str, Any]) -> list[str]:
    """Render one NIH aim entry, or nothing when not a dict."""
    if not isinstance(aim, dict):
        return []
    lines = [f"### {aim.get('aim', '')}\n"]
    rationale = aim.get("rationale", "")
    if rationale:
        lines.append(f"**Rationale:** {rationale}\n")
    approach = aim.get("approach", "")
    if approach:
        lines.append(f"**Approach:** {approach}\n")
    return lines


def _has_aims_content(
    introduction: str | None, aims: list[Any], impact: str | None
) -> bool:
    """Return whether the NIH aims section has any renderable content."""
    return bool(introduction or aims or impact)


def _render_aims_list(aims: list[Any]) -> list[str]:
    """Render each NIH aim entry in sequence."""
    lines: list[str] = []
    for aim in aims:
        lines += _render_nih_aim(aim)
    return lines


def _render_impact(impact: str | None) -> list[str]:
    """Render the 'Impact' subsection, or nothing when absent."""
    return ["### Impact\n", f"{impact}\n"] if impact else []


def _render_nih_aims_section(aims_section: dict[str, Any]) -> list[str]:
    """Render the 'NIH Specific Aims' section, or nothing when data absent."""
    if not isinstance(aims_section, dict):
        return []
    introduction = aims_section.get("introduction")
    aims = aims_section.get("aims") or []
    impact = aims_section.get("impact")
    if not _has_aims_content(introduction, aims, impact):
        return []
    lines = ["\n## NIH Specific Aims\n"]
    lines += _render_optional_paragraph(introduction)
    lines += _render_aims_list(aims)
    lines += _render_impact(impact)
    return lines


def render_research_overview_markdown(overview: dict[str, Any]) -> list[str]:
    """Render the research overview + NIH Specific Aims as markdown lines.

    Args:
        overview: The engine ``research_overview`` payload, shaped as
            ``{"overview": {...}, "nih_specific_aims": {...}}``. May be empty
            or carry empty sub-dicts for runs without hypotheses.

    Returns:
        A list of markdown lines. Empty when no renderable content exists, so
        callers never emit bare section headers.
    """
    # The isinstance guard here (and inside each section renderer) is
    # defensive: this payload can originate from LLM-produced structured
    # output (engine path), which is schema-validated but still worth
    # guarding defensively against a malformed or missing sub-shape rather
    # than raising here.
    if not isinstance(overview, dict):
        return []
    lines = _render_overview_section(overview.get("overview") or {})
    lines += _render_nih_aims_section(overview.get("nih_specific_aims") or {})
    return lines


def build_report_payload(
    *,
    research_goal: str,
    run_mode: str,
    provider: str,
    leaderboard: list[dict[str, Any]],
    hypothesis_count: int,
    evidence_count: int,
    match_count: int,
    citation_summary: dict[str, int] | None,
    meta_review: dict[str, Any] | None,
    research_overview: dict[str, Any] | None,
    execution_time: float | None = None,
) -> dict[str, Any]:
    """Assemble the canonical report payload shared by every provider.

    Both providers emit the same field set so the persisted report -- and the
    frontend ``ReportPayload`` type reading it -- has one shape regardless of
    which provider ran.

    Args:
        research_goal: The natural-language research goal.
        run_mode: Canonical run mode.
        provider: ``"engine"`` or ``"mock"``.
        leaderboard: Elo standings snapshot from ``live_leaderboard``.
        hypothesis_count: Number of hypotheses persisted for the run.
        evidence_count: Number of evidence rows persisted.
        match_count: Number of tournament matches persisted.
        citation_summary: Citation state -> count, or None when unavailable.
        meta_review: Meta-review synthesis dict, or None.
        research_overview: Research-overview payload, or None.
        execution_time: Wall-clock seconds, when the provider tracks it.

    Returns:
        The canonical report payload dict.
    """
    payload: dict[str, Any] = {
        "research_goal": research_goal,
        "run_mode": run_mode,
        "provider": provider,
        "hypothesis_count": hypothesis_count,
        "evidence_count": evidence_count,
        "match_count": match_count,
        "citation_summary": citation_summary or {},
        "leaderboard": leaderboard,
        "meta_review": meta_review or {},
        "research_overview": research_overview or {},
    }
    if execution_time is not None:
        payload["execution_time"] = execution_time
    return payload


def _render_recommendation(rec: dict[str, Any] | str) -> list[str]:
    """Render one strategic recommendation entry.

    Structured (dict) recommendations render with a rationale; a bare string
    falls back to a plain bullet.
    """
    if isinstance(rec, dict):
        area = rec.get("focus_area", "")
        recommendation = rec.get("recommendation", "")
        lines = [f"**{area}**: {recommendation}"]
        justification = rec.get("justification", "")
        if justification:
            lines.append(f"  *{justification}*")
        return lines
    return [f"- {rec}"]


def _render_bullet_list(heading: str, items: list[Any]) -> list[str]:
    """Render a heading and its bullet items, or nothing when empty."""
    if not items:
        return []
    return [f"\n{heading}\n"] + [f"- {item}" for item in items]


_META_REVIEW_BULLET_SECTIONS = (
    ("common_strengths", "### Common strengths"),
    ("common_weaknesses", "### Common weaknesses"),
    ("emerging_themes", "### Emerging themes"),
)


def _render_strategic_recommendations(recs: list[Any]) -> list[str]:
    """Render the 'Strategic recommendations' section, or nothing when empty."""
    if not recs:
        return []
    lines = ["\n### Strategic recommendations\n"]
    for rec in recs:
        lines += _render_recommendation(rec)
    return lines


def _render_meta_review_markdown(meta_review: dict[str, Any]) -> list[str]:
    """Render the meta-review insights section, or nothing when absent."""
    if not meta_review:
        return []
    lines = ["\n## Meta-review insights\n"]
    lines += _render_optional_paragraph(meta_review.get("summary"))
    for section_key, heading in _META_REVIEW_BULLET_SECTIONS:
        lines += _render_bullet_list(
            heading, meta_review.get(section_key) or []
        )
    lines += _render_strategic_recommendations(
        meta_review.get("strategic_recommendations") or []
    )
    return lines


def _first(*values: str | None) -> str:
    """Return the first truthy value among values, or "" when all falsy."""
    for value in values:
        if value:
            return value
    return ""


def _render_hypothesis_entry(i: int, hyp: dict[str, Any]) -> list[str]:
    """Render one numbered 'Top hypotheses' entry."""
    # "title"/"statement" are store row field names; "text" is the raw
    # engine hypothesis field name -- fall back across both so this renders
    # whichever shape the caller happens to pass in.
    title = _first(hyp.get("title"), hyp.get("text")) or "Untitled"
    lines = [f"### {i}. {title}  _Elo: {hyp.get('elo_rating', '')}_"]
    statement = _first(hyp.get("statement"), hyp.get("text"))
    if statement:
        lines += [statement, ""]
    for label, value in (
        ("**Mechanism:**", hyp.get("mechanism")),
        ("**Expected effect:**", hyp.get("expected_effect")),
    ):
        if value:
            lines += [f"{label} {value}", ""]
    return lines


def _render_top_hypotheses_markdown(
    top_hypotheses: list[dict[str, Any]],
) -> list[str]:
    """Render the numbered 'Top hypotheses' section."""
    lines: list[str] = ["## Top hypotheses", ""]
    for i, hyp in enumerate(top_hypotheses, 1):
        lines += _render_hypothesis_entry(i, hyp)
    return lines


def _render_citation_audit(
    citation_summary: dict[str, int] | None,
) -> list[str]:
    """Render the 'Citation audit' section, or nothing when absent."""
    if not citation_summary:
        return []
    lines = ["## Citation audit"]
    lines.extend(
        f"- {state}: {count}" for state, count in citation_summary.items()
    )
    lines.append("")
    return lines


def render_report_markdown(
    *,
    research_goal: str,
    provider: str,
    top_hypotheses: list[dict[str, Any]],
    meta_review: dict[str, Any] | None,
    citation_summary: dict[str, int] | None,
    research_overview: dict[str, Any] | None,
    summary: str | None = None,
) -> str:
    """Render a run's report markdown from one skeleton for every provider.

    Sections populate only when their data is present, so a provider that omits
    meta-review, citations, or a research overview simply skips those headings
    rather than emitting empty ones.

    Args:
        research_goal: The natural-language research goal.
        provider: ``"engine"`` or ``"mock"``.
        top_hypotheses: Elo-ordered store hypothesis rows (title, statement,
            mechanism, expected_effect, elo_rating).
        meta_review: Meta-review synthesis dict, or None.
        citation_summary: Citation state -> count, or None.
        research_overview: Research-overview payload, or None.
        summary: Optional lead paragraph rendered under a ``## Summary``
            heading (e.g. the mock's deterministic-mode disclaimer).

    Returns:
        The rendered markdown document.
    """
    lines: list[str] = [
        f"# Research Report — {research_goal}",
        "",
        f"_Provider: **{provider}**_",
        "",
    ]
    if summary:
        lines += ["## Summary", summary, ""]

    lines += _render_top_hypotheses_markdown(top_hypotheses)
    lines += _render_meta_review_markdown(meta_review or {})
    lines += _render_citation_audit(citation_summary)
    lines.extend(render_research_overview_markdown(research_overview or {}))
    return "\n".join(lines)


def _build_report_content(
    *,
    run_id: str,
    research_goal: str,
    run_mode: str,
    provider: str,
    citation_summary: dict[str, int] | None,
    meta_review: dict[str, Any] | None,
    research_overview: dict[str, Any] | None,
    execution_time: float | None,
    summary: str | None,
    db_path: str | None,
) -> tuple[dict[str, Any], str]:
    """Gather store data and build the report payload and markdown.

    Leaderboard, top hypotheses, and every row count are read from the store
    -- the drain has already persisted everything the payload counts, so the
    counts have one definition across providers.

    Args:
        run_id: Identifier of the run being finalized.
        research_goal: The natural-language research goal.
        run_mode: Canonical run mode.
        provider: ``"engine"`` or ``"mock"``.
        citation_summary: Citation state -> count, or None.
        meta_review: Meta-review synthesis dict, or None.
        research_overview: Research-overview payload, or None.
        execution_time: Wall-clock seconds, when the provider tracks it.
        summary: Optional lead paragraph for the markdown ``## Summary``.
        db_path: Optional override for the SQLite database path.

    Returns:
        A tuple of (report payload, rendered markdown).
    """
    hyps = store.list_hypotheses(run_id, db_path=db_path)
    counts = store.summary_counts(run_id, db_path=db_path)
    leaderboard = live_leaderboard(hyps)
    payload = build_report_payload(
        research_goal=research_goal,
        run_mode=run_mode,
        provider=provider,
        leaderboard=leaderboard,
        hypothesis_count=len(hyps),
        evidence_count=counts["evidence"],
        match_count=counts["matches"],
        citation_summary=citation_summary,
        meta_review=meta_review,
        research_overview=research_overview,
        execution_time=execution_time,
    )
    markdown = render_report_markdown(
        research_goal=research_goal,
        provider=provider,
        # Report body is capped to the top 5 by Elo; the full set remains
        # available via the leaderboard and the hypotheses API endpoint.
        top_hypotheses=hyps[:5],
        meta_review=meta_review,
        citation_summary=citation_summary,
        research_overview=research_overview,
        summary=summary,
    )
    return payload, markdown


async def finalize_report(
    *,
    run_id: str,
    research_goal: str,
    run_mode: str,
    provider: str,
    citation_summary: dict[str, int] | None,
    meta_review: dict[str, Any] | None,
    research_overview: dict[str, Any] | None,
    emit: EmitFn,
    execution_time: float | None = None,
    summary: str | None = None,
    db_path: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Build, screen, persist, and emit a run's final report.

    This is the single finalize path both providers invoke after their drain,
    so the final safety gate and the report/completed emission live in one
    place. Leaderboard, top hypotheses, and every row count are read from the
    store -- the drain has already persisted everything the payload counts, so
    the counts have one definition across providers.

    Order matches the shared contract: build payload -> render markdown ->
    screen_final + apply_safety_gate -> (unless blocked) save report -> emit
    report -> mark completed. A hard block records the blocked status via the
    safety gate and returns without persisting a report.

    Args:
        run_id: Identifier of the run being finalized.
        research_goal: The natural-language research goal.
        run_mode: Canonical run mode.
        provider: ``"engine"`` or ``"mock"``.
        citation_summary: Citation state -> count, or None.
        meta_review: Meta-review synthesis dict, or None.
        research_overview: Research-overview payload, or None.
        emit: The provider's event emitter, called as ``emit(type, payload)``.
        execution_time: Wall-clock seconds, when the provider tracks it.
        summary: Optional lead paragraph for the markdown ``## Summary``.
        db_path: Optional override for the SQLite database path.

    Yields:
        Event dicts to forward on the workflow's event stream.
    """
    payload, markdown = _build_report_content(
        run_id=run_id,
        research_goal=research_goal,
        run_mode=run_mode,
        provider=provider,
        citation_summary=citation_summary,
        meta_review=meta_review,
        research_overview=research_overview,
        execution_time=execution_time,
        summary=summary,
        db_path=db_path,
    )

    final = screen_final(markdown)
    async for event in apply_safety_gate(run_id, final, emit, db_path=db_path):
        yield event
    if final.decision == "block":
        return

    saved = store.save_report(run_id, payload, markdown, db_path=db_path)
    yield await emit("report", {**payload, "report_id": saved["id"]})
    store.update_run_status(run_id, RunStatus.COMPLETED, db_path=db_path)
    yield await emit("status", {"status": "completed"})
