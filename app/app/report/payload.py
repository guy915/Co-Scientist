"""Goal Report payload: the JSON the frontend reads, and the critique text.

Homed separately from ``engine_adapter`` so the report payload has one
implementation, matching the persisted report and the frontend
``ReportPayload`` type it reads (the rendered markdown lives in
``report.markdown``). Every function here is pure: it depends only on the
data passed in, never on the store or the safety gate.
``format_deep_verification_critique`` is the formatter the final-state drain
uses to persist deep-verification probes as a review.
"""

from __future__ import annotations

import dataclasses
from typing import Any


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


@dataclasses.dataclass(frozen=True)
class ReportPayloadInputs:
    """Everything the canonical report payload is assembled from.

    One bundle rather than fifteen parameters: the run's identity, its row
    counts, and each synthesized section travel together from the store
    reads in ``report.finalize`` all the way into the persisted payload.
    """

    research_goal: str
    run_mode: str
    provider: str
    leaderboard: list[dict[str, Any]]
    # Published ideas -- what survived the safety and contradiction gates.
    hypothesis_count: int
    # Every idea the run explored, gated or not. Distinct from
    # ``hypothesis_count`` on purpose: a run that explores 22 ideas and
    # publishes 2 has to be able to say both, and reporting the published
    # count as the explored one told readers "2 ideas were explored" beside
    # a list of 22.
    idea_count: int
    # Published ideas with an evidence-supported claim (see
    # ``_verified_hypothesis_count``).
    verified_count: int
    evidence_count: int
    match_count: int
    citation_summary: dict[str, int] | None = None
    meta_review: dict[str, Any] | None = None
    research_overview: dict[str, Any] | None = None
    knowledge_base: list[dict[str, Any]] | None = None
    agent_insights: dict[str, Any] | None = None
    idea_buckets: dict[str, list[dict[str, Any]]] | None = None
    claim_evidence: list[dict[str, Any]] | None = None
    execution_time: float | None = None


def build_report_payload(inputs: ReportPayloadInputs) -> dict[str, Any]:
    """Assemble the canonical report payload from its bundled inputs.

    Args:
        inputs: The run identity, row counts, and synthesized sections.

    Returns:
        The payload dict persisted as the run's report. ``execution_time``
        is present only when the caller supplied one.
    """
    payload: dict[str, Any] = {
        "research_goal": inputs.research_goal,
        "run_mode": inputs.run_mode,
        "provider": inputs.provider,
        "hypothesis_count": inputs.hypothesis_count,
        "idea_count": inputs.idea_count,
        "verified_count": inputs.verified_count,
        "evidence_count": inputs.evidence_count,
        "match_count": inputs.match_count,
        "leaderboard": inputs.leaderboard,
        "citation_summary": inputs.citation_summary or {},
        "meta_review": inputs.meta_review or {},
        "research_overview": inputs.research_overview or {},
        "knowledge_base": inputs.knowledge_base or [],
        "agent_insights": inputs.agent_insights or {},
        "idea_buckets": inputs.idea_buckets
        or {"high_potential": [], "non_viable": []},
        "claim_evidence": inputs.claim_evidence or [],
    }
    if inputs.execution_time is not None:
        payload["execution_time"] = inputs.execution_time
    return payload
