"""Report content builders: payload assembly and markdown rendering.

Homed separately from ``engine_adapter`` so the report payload and its
rendered markdown have one implementation, matching the persisted report and
the frontend ``ReportPayload`` type it reads. Every function here is pure: it
depends only on the data passed in, never on the store or the safety gate.
"""

from __future__ import annotations

import dataclasses
from typing import Any

# The run-wide bibliography (R12-12) lives in its own module to keep
# report_markdown_documents within the size cap; the name is re-exported so
# this module's namespace keeps resolving.
from app.report_markdown_bibliography import (
    _render_references_section as _render_references_section,
)
from app.report_markdown_documents import (
    _NOVELTY_DISCLOSURE as _NOVELTY_DISCLOSURE,
)

# The two document assemblers (R14-11: Research Overview and Top Ranking
# Hypotheses) and the input bundle they render from live in their own
# module to keep this one within the size cap; every name is re-exported
# so this module's namespace keeps resolving.
from app.report_markdown_documents import (
    ReportMarkdownInputs as ReportMarkdownInputs,
)
from app.report_markdown_documents import (
    _any_novelty_verified as _any_novelty_verified,
)
from app.report_markdown_documents import (
    _claim_evidence_by_hypothesis as _claim_evidence_by_hypothesis,
)
from app.report_markdown_documents import (
    _overview_sections as _overview_sections,
)
from app.report_markdown_documents import (
    _ranking_sections as _ranking_sections,
)
from app.report_markdown_documents import (
    _render_citation_audit as _render_citation_audit,
)
from app.report_markdown_documents import (
    _render_novelty_disclosure as _render_novelty_disclosure,
)
from app.report_markdown_documents import (
    _render_top_hypotheses_markdown as _render_top_hypotheses_markdown,
)
from app.report_markdown_documents import (
    render_overview_document_markdown as render_overview_document_markdown,
)
from app.report_markdown_documents import (
    render_ranking_document_markdown as render_ranking_document_markdown,
)

# The header (title, provider line, Research Goal Details) lives in its
# own module to keep this one within the size cap; the names are
# re-exported so this module's namespace keeps resolving.
from app.report_markdown_header import (
    _render_about_disclosure as _render_about_disclosure,
)
from app.report_markdown_header import (
    _render_provenance_line as _render_provenance_line,
)
from app.report_markdown_header import (
    _render_research_goal_details as _render_research_goal_details,
)
from app.report_markdown_header import (
    _render_summary_section as _render_summary_section,
)
from app.report_markdown_header import (
    _render_title_and_provider as _render_title_and_provider,
)

# The per-hypothesis 'Top hypotheses' entry renderer (and its exclusive
# claim-evidence helpers) moved to its own module to keep this one within
# both the line-count and mccabe-complexity caps; every moved name is
# re-exported so this module's namespace keeps resolving.
from app.report_markdown_hypothesis import _claim_status as _claim_status
from app.report_markdown_hypothesis import (
    _render_claim_evidence as _render_claim_evidence,
)
from app.report_markdown_hypothesis import (
    _render_evidence_span as _render_evidence_span,
)
from app.report_markdown_hypothesis import (
    _render_hypothesis_entry as _render_hypothesis_entry,
)
from app.report_markdown_hypothesis import (
    _render_hypothesis_experiment as _render_hypothesis_experiment,
)
from app.report_markdown_hypothesis import (
    _render_hypothesis_mechanism as _render_hypothesis_mechanism,
)
from app.report_markdown_hypothesis import (
    _render_hypothesis_safety as _render_hypothesis_safety,
)
from app.report_markdown_hypothesis import (
    _render_hypothesis_scene_setting as _render_hypothesis_scene_setting,
)
from app.report_markdown_hypothesis import (
    _render_top_ranking_hypotheses_list as _render_top_ranking_hypotheses_list,
)
from app.report_markdown_hypothesis import (
    _reviews_by_hypothesis as _reviews_by_hypothesis,
)

# The knowledge-base section lives in its own module to keep this one
# within the size cap; the name is re-exported so this module's namespace
# keeps resolving.
from app.report_markdown_knowledge_base import (
    _render_knowledge_base_markdown as _render_knowledge_base_markdown,
)

# The meta-review insights section moved to its own module to keep this
# one within the size cap; every moved name is re-exported so this
# module's namespace keeps resolving. Split in two (R14-11): the overview
# document's cross-run synthesis and the ranking document's tournament
# comparison share the same source payload but render onto different
# documents.
from app.report_markdown_meta_review import (
    _render_meta_review_overview_markdown as _render_meta_review_overview_markdown,  # noqa: E501
)
from app.report_markdown_meta_review import (
    _render_meta_review_ranking_markdown as _render_meta_review_ranking_markdown,  # noqa: E501
)

# The research-overview/NIH-aims/contacts renderers moved verbatim to
# ``report_markdown_overview``; every moved name is re-exported so this
# module's namespace keeps resolving.
from app.report_markdown_overview import (
    _has_aims_content as _has_aims_content,
)
from app.report_markdown_overview import (
    _has_overview_content as _has_overview_content,
)
from app.report_markdown_overview import (
    _render_aims_list as _render_aims_list,
)
from app.report_markdown_overview import (
    _render_directions_list as _render_directions_list,
)
from app.report_markdown_overview import (
    _render_experiments_list as _render_experiments_list,
)
from app.report_markdown_overview import (
    _render_nih_aim as _render_nih_aim,
)
from app.report_markdown_overview import (
    _render_nih_aims_section as _render_nih_aims_section,
)
from app.report_markdown_overview import (
    _render_optional_paragraph as _render_optional_paragraph,
)
from app.report_markdown_overview import (
    _render_overview_section as _render_overview_section,
)
from app.report_markdown_overview import (
    _render_research_contacts_section as _render_research_contacts_section,
)
from app.report_markdown_overview import (
    _render_research_direction as _render_research_direction,
)
from app.report_markdown_overview import (
    render_research_overview_markdown as render_research_overview_markdown,
)
from app.report_markdown_overview import (
    research_overview_sections as research_overview_sections,
)

# The per-hypothesis References subsection (resolving [C*] citation keys)
# lives in its own module to keep this one within the size cap; both names
# are re-exported so this module's namespace keeps resolving.
from app.report_markdown_references import (
    _render_references_markdown as _render_references_markdown,
)
from app.report_markdown_references import (
    references_by_hypothesis as references_by_hypothesis,
)

# The data-sources section (skill attribution + literature-search summary)
# moved to its own module to keep this one within the size cap; both names
# are re-exported so this module's namespace keeps resolving.
from app.report_markdown_sources import (
    _render_data_source_notice as _render_data_source_notice,
)
from app.report_markdown_sources import (
    _render_data_sources_section as _render_data_sources_section,
)

# The Supervisor's synthesized guidance sections (stratification
# attributes, evaluation criteria, the review rubric) live in their own
# module to keep this one within the size cap; every name is re-exported
# so this module's namespace keeps resolving.
from app.report_markdown_supervisor import (
    _render_evaluation_criteria_markdown as _render_evaluation_criteria_markdown,  # noqa: E501
)
from app.report_markdown_supervisor import (
    _render_review_summary_markdown as _render_review_summary_markdown,
)
from app.report_markdown_supervisor import (
    _render_stratification_attributes_markdown as _render_stratification_attributes_markdown,  # noqa: E501
)

# The table-of-contents renderer (R14-1) lives in its own module to keep
# this one within the size cap; the name is re-exported so this module's
# namespace keeps resolving.
from app.report_markdown_toc import (
    _render_table_of_contents as _render_table_of_contents,
)


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
    reads in ``report_render`` all the way into the persisted payload.
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
