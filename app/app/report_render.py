"""Shared report-rendering and event-payload helpers.

Homed here (rather than inside a single provider) so both the real-engine
drain (``engine_adapter``) and the deterministic mock (``mock_workflow``) render
the research overview, deep-verification critique, and event-payload stubs
through one implementation -- keeping the persisted report and the streamed
event shapes identical across providers.
"""

from __future__ import annotations

from typing import Any


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


def format_deep_verification_critique(probes: list[dict[str, Any]],
                                      verdict: str | None) -> tuple[str, str]:
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
        question = str(probe.get("question", "")).strip()
        answer = str(probe.get("answer", "")).strip()
        reasoning = str(probe.get("reasoning", "")).strip()
        fundamental = bool(probe.get("assumption_is_fundamental"))
        flag = "fundamental" if fundamental else "non-fundamental"
        lines.append(f"Probe {idx} ({flag} assumption):")
        if question:
            lines.append(f"  Question: {question}")
        if answer:
            lines.append(f"  Answer: {answer}")
        if reasoning:
            lines.append(f"  Reasoning: {reasoning}")
        lines.append("")
    critique = "\n".join(lines).strip()
    return summary, critique


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
    lines: list[str] = []
    if not isinstance(overview, dict):
        return lines

    ov = overview.get("overview") or {}
    if isinstance(ov, dict):
        summary = ov.get("summary")
        directions = ov.get("research_directions") or []
        if summary or directions:
            lines.append("\n## Research Overview\n")
            if summary:
                lines.append(f"{summary}\n")
            for direction in directions:
                if not isinstance(direction, dict):
                    continue
                title = direction.get("title", "")
                importance = direction.get("importance", "")
                experiments = direction.get("suggested_experiments") or []
                lines.append(f"### {title}\n")
                if importance:
                    lines.append(f"{importance}\n")
                if experiments:
                    lines.append("Suggested experiments:\n")
                    for experiment in experiments:
                        lines.append(f"- {experiment}")
                    lines.append("")

    aims_section = overview.get("nih_specific_aims") or {}
    if isinstance(aims_section, dict):
        introduction = aims_section.get("introduction")
        aims = aims_section.get("aims") or []
        impact = aims_section.get("impact")
        if introduction or aims or impact:
            lines.append("\n## NIH Specific Aims\n")
            if introduction:
                lines.append(f"{introduction}\n")
            for aim in aims:
                if not isinstance(aim, dict):
                    continue
                aim_text = aim.get("aim", "")
                rationale = aim.get("rationale", "")
                approach = aim.get("approach", "")
                lines.append(f"### {aim_text}\n")
                if rationale:
                    lines.append(f"**Rationale:** {rationale}\n")
                if approach:
                    lines.append(f"**Approach:** {approach}\n")
            if impact:
                lines.append("### Impact\n")
                lines.append(f"{impact}\n")
    return lines
