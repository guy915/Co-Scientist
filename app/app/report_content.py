"""Report content derivation split out of ``report_render``.

Holds the pure data-shaping helpers the report builder composes: knowledge-
base topic builders, agent-insight and idea-bucket derivation, claim-evidence
enrichment, and the exclusion filters (contradicted/unverified/unsafe). The
finalize path -- ``_build_report_content`` and ``finalize_report`` -- stays in
``report_render``, which re-exports every name here so callers keep a single
``app.report_render`` import surface.
"""

from __future__ import annotations

import logging
from typing import Any

from app import store
from app.hypothesis_safety import (
    is_blocking_status,
    review_hypothesis_safety,
)
from app.hypothesis_screening import record_hypothesis_block

logger = logging.getLogger(__name__)


def _knowledge_base_topics(
    hypotheses: list[dict[str, Any]],
    claim_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build named technical topics from released hypotheses and claim links."""
    references_by_hypothesis: dict[str, list[str]] = {}
    for edge in claim_edges:
        if edge.get("label") != "supports":
            continue
        hypothesis_id = str(edge.get("hypothesis_id") or "")
        evidence_id = str(edge.get("evidence_id") or "")
        if evidence_id:
            references_by_hypothesis.setdefault(hypothesis_id, []).append(
                evidence_id
            )
    topics: list[dict[str, Any]] = []
    for hypothesis in hypotheses[:8]:
        hypothesis_id = str(hypothesis.get("id") or "")
        topics.append(
            {
                "id": f"topic-{hypothesis_id}",
                "title": str(hypothesis.get("title") or "Mechanistic finding"),
                "summary": str(
                    hypothesis.get("mechanism")
                    or hypothesis.get("statement")
                    or ""
                ),
                "detail": str(
                    hypothesis.get("experimental_context")
                    or hypothesis.get("expected_effect")
                    or ""
                ),
                "reference_ids": sorted(
                    set(references_by_hypothesis.get(hypothesis_id, []))
                ),
            }
        )
    return topics


def _synthesized_knowledge_base_topics(
    research_overview: dict[str, Any] | None,
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map engine-synthesized source titles to durable evidence identifiers."""
    if not isinstance(research_overview, dict):
        return []
    raw_topics = research_overview.get("knowledge_base")
    if not isinstance(raw_topics, list):
        return []
    evidence_id_by_title = {
        str(item.get("title") or ""): str(item.get("id") or "")
        for item in evidence
    }
    topics: list[dict[str, Any]] = []
    for raw in raw_topics:
        if not isinstance(raw, dict):
            continue
        references = raw.get("references") or []
        reference_ids = sorted(
            {
                evidence_id_by_title.get(str(ref.get("title") or ""), "")
                for ref in references
                if isinstance(ref, dict)
            }
            - {""}
        )
        if not reference_ids:
            continue
        topics.append(
            {
                "id": str(raw.get("id") or f"topic-{len(topics) + 1}"),
                "title": str(raw.get("title") or "Technical topic"),
                "summary": str(raw.get("summary") or ""),
                "detail": str(raw.get("detail") or ""),
                "uncertainty": str(raw.get("uncertainty") or ""),
                "reference_ids": reference_ids,
            }
        )
    return topics


def _agent_insights(
    hypotheses: list[dict[str, Any]],
    claim_edges: list[dict[str, Any]],
    meta_review: dict[str, Any] | None,
) -> dict[str, Any]:
    """Derive visible findings, uncertainty, contradictions, and experiments."""
    meta = meta_review or {}
    return {
        "key_findings": [
            "Proposed hypothesis: "
            + str(hypothesis.get("statement") or hypothesis.get("title") or "")
            for hypothesis in hypotheses[:5]
        ],
        "uncertainties": [
            str(item) for item in meta.get("common_weaknesses", [])
        ],
        "contradictions": [
            str(edge.get("claim_text") or edge.get("claim_id") or "")
            for edge in claim_edges
            if edge.get("label") == "contradicts"
        ],
        "recommended_directions": [
            str(item) for item in meta.get("strategic_recommendations", [])
        ],
        "next_experiments": [
            str(hypothesis.get("experimental_context") or "")
            for hypothesis in hypotheses[:5]
            if hypothesis.get("experimental_context")
        ],
    }


def _claim_edge_reasons(
    claim_edges: list[dict[str, Any]],
) -> dict[str, set[str]]:
    """Map hypothesis id -> reasons its claims were not fully supported."""
    edge_reasons: dict[str, set[str]] = {}
    for edge in claim_edges:
        if edge.get("label") == "supports" or (
            edge.get("label") == "insufficient"
            and edge.get("claim_role") == "speculative"
        ):
            continue
        edge_reasons.setdefault(str(edge.get("hypothesis_id")), set()).add(
            "Evidence verification did not support every material claim."
        )
    return edge_reasons


def _high_potential_bucket(
    safe_hypotheses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the 'high_potential' idea bucket from the top safe hypotheses."""
    return [
        {
            "id": str(hypothesis.get("id")),
            "title": str(hypothesis.get("title") or "Untitled idea"),
            "reason": (
                "Released by safety and evidence gates and ranked by Elo."
            ),
        }
        for hypothesis in safe_hypotheses[:5]
    ]


def _non_viable_reasons(
    hypothesis: dict[str, Any], edge_reasons: dict[str, set[str]]
) -> list[str]:
    """Return the excluded-idea reasons for one non-viable hypothesis."""
    hypothesis_id = str(hypothesis.get("id"))
    reasons = sorted(edge_reasons.get(hypothesis_id, set()))
    if is_blocking_status(str(hypothesis.get("safety_status") or "")):
        reasons.append("The scientific safety review blocked this idea.")
    # Under rank-and-publish an idea only leaves the ranked report when it
    # is contradicted (an edge reason above), blocked by safety, or set
    # aside during review/deduplication -- never for being merely
    # unsupported (those are published and badged "Unverified").
    if not reasons and hypothesis.get("status") == "rejected":
        reasons.append(
            "Set aside during review as inaccurate, non-novel, or a "
            "near-duplicate of a higher-ranked idea."
        )
    return reasons


def _non_viable_bucket(
    all_hypotheses: list[dict[str, Any]],
    safe_ids: set[str],
    edge_reasons: dict[str, set[str]],
) -> list[dict[str, Any]]:
    """Build the 'non_viable' idea bucket for every excluded hypothesis."""
    non_viable = []
    for hypothesis in all_hypotheses:
        hypothesis_id = str(hypothesis.get("id"))
        if hypothesis_id in safe_ids:
            continue
        reasons = _non_viable_reasons(hypothesis, edge_reasons)
        non_viable.append(
            {
                "id": hypothesis_id,
                "title": str(hypothesis.get("title") or "Untitled idea"),
                "reason": " ".join(reasons)
                or "Withheld from the ranked report.",
            }
        )
    return non_viable


def _idea_buckets(
    safe_hypotheses: list[dict[str, Any]],
    all_hypotheses: list[dict[str, Any]],
    claim_edges: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Classify released leaders and excluded ideas with explicit reasons."""
    safe_ids = {str(hypothesis.get("id")) for hypothesis in safe_hypotheses}
    edge_reasons = _claim_edge_reasons(claim_edges)
    return {
        "high_potential": _high_potential_bucket(safe_hypotheses),
        "non_viable": _non_viable_bucket(
            all_hypotheses, safe_ids, edge_reasons
        ),
    }


def _released_claim_evidence(
    hypotheses: list[dict[str, Any]],
    claim_edges: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach source titles to claim spans for hypotheses in the report."""
    released_ids = {
        str(hypothesis.get("id") or "") for hypothesis in hypotheses
    }
    sources = {
        str(item.get("id") or ""): item for item in evidence if item.get("id")
    }
    released: list[dict[str, Any]] = []
    for edge in claim_edges:
        if str(edge.get("hypothesis_id") or "") not in released_ids:
            continue
        enriched = dict(edge)
        for key in ("supporting", "contradicting"):
            spans: list[Any] = []
            for raw_span in edge.get(key) or []:
                if not isinstance(raw_span, dict):
                    spans.append(raw_span)
                    continue
                span = dict(raw_span)
                source = sources.get(str(span.get("evidence_id") or ""), {})
                span["source_title"] = str(
                    span.get("source_title") or source.get("title") or ""
                )
                span["source"] = str(
                    span.get("source") or source.get("source") or ""
                )
                span["url"] = str(span.get("url") or source.get("url") or "")
                spans.append(span)
            enriched[key] = spans
        released.append(enriched)
    return released


def _contradicted_hypothesis_ids(
    run_id: str,
    db_path: str | None,
    claim_edges: list[dict[str, Any]] | None = None,
) -> set[str]:
    """Ids of hypotheses with a claim the evidence contradicts.

    Contradicted ideas have evidence *against* them, so the rank-and-publish
    policy withholds them from the report entirely -- unlike merely-unsupported
    ideas, which are published with an "Unverified" badge.

    ``claim_edges`` may be passed to reuse an already-fetched edge list;
    when omitted it is queried from the store.
    """
    edges = (
        claim_edges
        if claim_edges is not None
        else store.list_claim_evidence(run_id, db_path=db_path)
    )
    return {
        str(edge["hypothesis_id"])
        for edge in edges
        if edge.get("label") == "contradicts"
    }


def _unverified_hypothesis_ids(
    run_id: str,
    db_path: str | None,
    hyps: list[dict[str, Any]] | None = None,
) -> set[str]:
    """Ids of published hypotheses that lack an evidence-supported claim.

    A hypothesis is "verified" once at least one of its claims has a
    ``supports`` evidence edge. Under the rank-and-publish policy the rest are
    still ranked and published, but flagged "Unverified" in the report and the
    idea list rather than blocking the run.

    When a run has no claim-evidence edges at all -- claim grounding never ran,
    as for mock demo runs -- none of its ideas were assessed, so none is
    reported unverified (the badge means "assessed and unsupported", not
    "not yet assessed").

    ``hyps`` may be passed to reuse an already-fetched hypothesis list;
    when omitted it is queried from the store.
    """
    edges = store.list_claim_evidence(run_id, db_path=db_path)
    if not edges:
        return set()
    supported = {
        str(edge["hypothesis_id"])
        for edge in edges
        if edge.get("label") == "supports"
    }
    rows = (
        hyps
        if hyps is not None
        else store.list_hypotheses(run_id, db_path=db_path)
    )
    all_hypothesis_ids = {str(hypothesis.get("id")) for hypothesis in rows}
    return all_hypothesis_ids - supported


def _exclude_unsafe_hypotheses(
    run_id: str,
    hyps: list[dict[str, Any]],
    db_path: str | None,
    claim_edges: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Drop hypotheses a safety review or the publication gate blocks.

    Milestone 5/6/M9 wiring: a hypothesis whose safety review is prohibited/
    ethical/uncertain (SSR §1, §10) or whose claims are contradicted by the
    evidence (the publication gate, SSR §7) must not appear in the final
    report's leaderboard or top ideas. The pre-tournament screen and claim
    grounding already persisted each hypothesis's ``safety_status`` and
    claim-evidence graph and recorded their audit rows, so the common path just
    honors those. A legacy row with no persisted safety status (older runs) is
    re-reviewed and audited here as a fallback. Benign hypotheses pass through
    unchanged.

    Args:
        run_id: The run whose report is being built.
        hyps: The run's hypotheses (store rows with a ``statement`` and,
            normally, a persisted ``safety_status``).
        db_path: Optional override for the SQLite database path.
        claim_edges: Pre-fetched claim-evidence edges to reuse; queried from
            the store when omitted.

    Returns:
        The hypotheses safe to synthesize, in the original order.
    """
    contradicted = _contradicted_hypothesis_ids(run_id, db_path, claim_edges)
    return [
        hyp
        for hyp in hyps
        if _hypothesis_passes_safety_gate(run_id, hyp, contradicted, db_path)
    ]


def _hypothesis_passes_safety_gate(
    run_id: str,
    hyp: dict[str, Any],
    contradicted: set[str],
    db_path: str | None,
) -> bool:
    """Return whether one hypothesis clears the contradiction/safety gate."""
    if hyp.get("status") == "rejected":
        return False
    # Contradicted ideas have evidence against them and are withheld
    # entirely; merely-unsupported ideas are published with an "Unverified"
    # badge (see _unverified_hypothesis_ids), not excluded here.
    if str(hyp.get("id")) in contradicted:
        logger.warning(
            "Excluding hypothesis %s from synthesis: contradicted claim",
            hyp.get("id"),
        )
        return False
    status = hyp.get("safety_status")
    # Common path: the screen already decided; honor the persisted status
    # without re-reviewing or double-recording the audit row.
    if status and status != "pending":
        if is_blocking_status(str(status)):
            logger.warning(
                "Excluding hypothesis %s from synthesis: %s",
                hyp.get("id"),
                status,
            )
            return False
        return True
    return _legacy_hypothesis_passes_safety_gate(run_id, hyp, db_path)


def _legacy_hypothesis_passes_safety_gate(
    run_id: str, hyp: dict[str, Any], db_path: str | None
) -> bool:
    """Re-review and audit a row the pre-tournament screen never touched."""
    review = review_hypothesis_safety(str(hyp.get("statement") or ""))
    if not review.blocks_tournament:
        return True
    record_hypothesis_block(run_id, hyp.get("id"), review, db_path=db_path)
    logger.warning(
        "Excluding hypothesis %s from synthesis: %s",
        hyp.get("id"),
        review.outcome.value,
    )
    return False
