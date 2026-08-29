"""Report content builders: payload assembly and markdown rendering.

Homed separately from ``engine_adapter`` so the report payload and its
rendered markdown have one implementation, matching the persisted report and
the frontend ``ReportPayload`` type it reads. Every function here is pure: it
depends only on the data passed in, never on the store or the safety gate.
"""

from __future__ import annotations

import dataclasses
from typing import Any

# The header (title, provider line, Research Goal Details) lives in its
# own module to keep this one within the size cap; the names are
# re-exported so this module's namespace keeps resolving.
from app.report_markdown_header import (
    _render_provenance_line as _render_provenance_line,
)
from app.report_markdown_header import (
    _render_report_header as _render_report_header,
)
from app.report_markdown_header import (
    _render_research_goal_details as _render_research_goal_details,
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
    _render_hypothesis_mechanism as _render_hypothesis_mechanism,
)
from app.report_markdown_hypothesis import (
    _render_hypothesis_safety as _render_hypothesis_safety,
)
from app.report_markdown_hypothesis import (
    _render_hypothesis_scene_setting as _render_hypothesis_scene_setting,
)

# The knowledge-base section lives in its own module to keep this one
# within the size cap; the name is re-exported so this module's namespace
# keeps resolving.
from app.report_markdown_knowledge_base import (
    _render_knowledge_base_markdown as _render_knowledge_base_markdown,
)

# The meta-review insights section moved to its own module to keep this
# one within the size cap; every moved name is re-exported so this
# module's namespace keeps resolving.
from app.report_markdown_meta_review import (
    _render_meta_review_markdown as _render_meta_review_markdown,
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
    _render_contact_entry as _render_contact_entry,
)
from app.report_markdown_overview import (
    _render_contact_evidence_line as _render_contact_evidence_line,
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


def _claim_evidence_by_hypothesis(
    claim_evidence: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group claim edges by hypothesis id in one pass.

    The section renders up to five hypotheses and every edge belongs to
    exactly one of them, so grouping once beats re-filtering the whole edge
    list per entry.

    Args:
        claim_evidence: The run's released claim-evidence edges.

    Returns:
        Mapping of hypothesis id to its edges, in their original order.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for edge in claim_evidence:
        key = str(edge.get("hypothesis_id") or "")
        grouped.setdefault(key, []).append(edge)
    return grouped


# K3: novelty scores/language throughout the review, ranking, and
# generation prompts are the reviewing model's own unaided judgment --
# grounding that judgment in an actual literature search
# (novelty_validation, populated by
# co_scientist.agents.generation.literature_tools.validate_novelty) only
# runs on the tool-calling generation path, which the app never enables for
# a real run (see engine_adapter/opts.py). A reader must never be left with
# definitive novelty language on the strength of an unverified judgment, so
# this note renders whenever nothing in the report was actually corpus-
# checked -- which today is every run.
_NOVELTY_DISCLOSURE = (
    "_Novelty above reflects the reviewing model's own judgment, not a"
    " search of the published literature. Treat any claim that an idea is"
    " original, unprecedented, or unexplored as directional, not verified._"
)


def _any_novelty_verified(top_hypotheses: list[dict[str, Any]]) -> bool:
    """Return whether any hypothesis carries a corpus-checked novelty result.

    Real today only via the tool-calling generation path the app never
    enables (see the module-level note above), so this stays a genuine
    check -- not a hardcoded True -- so a future run that does enable that
    path stops rendering an inaccurate blanket disclosure without a code
    change here.
    """
    return any(hyp.get("novelty_validation") for hyp in top_hypotheses)


def _render_novelty_disclosure(
    top_hypotheses: list[dict[str, Any]],
) -> list[str]:
    """Render the novelty-unverified disclosure, unless corpus-checked."""
    if not top_hypotheses or _any_novelty_verified(top_hypotheses):
        return []
    return [_NOVELTY_DISCLOSURE, ""]


def _render_top_hypotheses_markdown(
    top_hypotheses: list[dict[str, Any]],
    claim_evidence: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> list[str]:
    """Render the numbered 'Top hypotheses' section."""
    edges_by_hypothesis = _claim_evidence_by_hypothesis(claim_evidence)
    refs_by_hypothesis = references_by_hypothesis(citations, evidence)
    lines: list[str] = ["## Top hypotheses", ""]
    lines += _render_novelty_disclosure(top_hypotheses)
    for i, hyp in enumerate(top_hypotheses, 1):
        hyp_id = str(hyp.get("id") or "")
        lines += _render_hypothesis_entry(
            i,
            hyp,
            edges_by_hypothesis.get(hyp_id, []),
            refs_by_hypothesis.get(hyp_id, []),
        )
    return lines


def _render_stratification_attributes_markdown(
    attributes: list[dict[str, Any]] | None,
) -> list[str]:
    """Render the Supervisor's synthesized 1-5 stratification attributes.

    R12-17: the Supervisor already synthesizes up to three named rating
    scales (``config_synthesis.attributes``, each a ``{name, rubric}``
    pair) and ``prompts/review.py`` already injects them into every
    reviewer prompt as "Stratification attributes (score each 1-5)" --
    this only displays what was already computed. Display only: never
    used here or anywhere else to gate, filter, rank, or disqualify a
    hypothesis.

    Deliberately not titled "Attributes" -- that heading already names the
    run's user-authored, plain-string setup attributes rendered under
    "Research Goal Details" (``report_markdown_header.py``). Google's own
    published documents use the same word for both a bare list and a
    name-plus-rubric section; reusing it here would conflate the two.
    """
    items = [
        attr
        for attr in attributes or []
        if isinstance(attr, dict) and str(attr.get("name") or "").strip()
    ]
    if not items:
        return []
    lines = ["## Stratification Attributes\n"]
    for attr in items:
        name = str(attr["name"]).strip()
        rubric = str(attr.get("rubric") or "").strip()
        lines.append(f"- **{name}:** {rubric}" if rubric else f"- **{name}**")
    lines.append("")
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


@dataclasses.dataclass(frozen=True)
class ReportMarkdownInputs:
    """Everything the report markdown document renders from.

    The prose counterpart of :class:`ReportPayloadInputs`: the same run
    identity plus the already-ranked hypotheses and the sections that have
    a rendered form.
    """

    research_goal: str
    provider: str
    top_hypotheses: list[dict[str, Any]]
    meta_review: dict[str, Any] | None = None
    citation_summary: dict[str, int] | None = None
    research_overview: dict[str, Any] | None = None
    knowledge_base: list[dict[str, Any]] | None = None
    # The run's persisted requirements/attributes/criteria (and goal),
    # rendered as "Research Goal Details" -- see run_modes.setup_config.
    setup: dict[str, Any] | None = None
    # The Supervisor's synthesized 1-5 stratification attributes
    # (config_synthesis.attributes), rendered as "Stratification
    # Attributes". A different, LLM-synthesized field from
    # setup["attributes"] above -- same English word, two differently-
    # shaped published sections (docs/CORPUS-EXTRACTION.md R12-17); do not
    # conflate them under one heading.
    attributes: list[dict[str, Any]] | None = None
    # Epoch seconds this report was built, rendered as the provenance and
    # research-purposes-only caution line. None omits that line entirely
    # rather than stating a date via the wall clock -- see
    # report_markdown_header._render_provenance_line.
    prepared_at: float | None = None
    summary: str | None = None
    claim_evidence: list[dict[str, Any]] | None = None
    skills_used: dict[str, int] | None = None
    retrieval_calls: list[dict[str, Any]] | None = None
    # Raw citations/evidence rows (store.list_citations / list_evidence),
    # joined per hypothesis by report_markdown_references to resolve the
    # [C*] keys the mechanism text cites. None (an old run rendered before
    # this field existed, or a run with no citation data at all) resolves
    # no keys -- the report never fabricates a reference.
    citations: list[dict[str, Any]] | None = None
    evidence: list[dict[str, Any]] | None = None


def render_report_markdown(inputs: ReportMarkdownInputs) -> str:
    """Render a run's report markdown from one skeleton for every provider.

    Sections populate only when their data is present, so a provider that
    omits meta-review, citations, or a research overview simply skips those
    headings rather than emitting empty ones.

    Args:
        inputs: The run identity, top hypotheses, and rendered sections.

    Returns:
        The rendered markdown document.
    """
    lines = _render_report_header(
        inputs.research_goal,
        inputs.provider,
        inputs.summary,
        inputs.setup,
        inputs.prepared_at,
    )
    lines += _render_stratification_attributes_markdown(inputs.attributes)
    lines += _render_top_hypotheses_markdown(
        inputs.top_hypotheses,
        inputs.claim_evidence or [],
        inputs.citations or [],
        inputs.evidence or [],
    )
    lines += _render_meta_review_markdown(inputs.meta_review or {})
    lines += _render_citation_audit(inputs.citation_summary)
    lines.extend(
        render_research_overview_markdown(inputs.research_overview or {})
    )
    lines += _render_knowledge_base_markdown(inputs.knowledge_base or [])
    lines += _render_data_sources_section(
        inputs.skills_used or {}, inputs.retrieval_calls or []
    )
    return "\n".join(lines)
