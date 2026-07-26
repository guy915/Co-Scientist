"""Report content derivation split out of ``report_render``.

Holds the pure data-shaping helpers the report builder composes: knowledge-
base topic builders, agent-insight and idea-bucket derivation, and claim-
evidence enrichment. The exclusion filters (contradicted/unverified/unsafe)
live in ``report_content_gates`` and are re-exported here. The finalize path
-- ``_build_report_content`` and ``finalize_report`` -- stays in
``report_render``, which re-exports every name here so callers keep a single
``app.report_render`` import surface.
"""

from __future__ import annotations

import logging
from typing import Any

from app.hypothesis_safety import is_blocking_status
from app.report_content_gates import (
    _contradicted_hypothesis_ids as _contradicted_hypothesis_ids,
)
from app.report_content_gates import (
    _exclude_unsafe_hypotheses as _exclude_unsafe_hypotheses,
)
from app.report_content_gates import (
    _hypothesis_passes_safety_gate as _hypothesis_passes_safety_gate,
)

# Re-exported so ``app.report_content`` keeps every name it exposed before
# the gates split; the redundant-alias form does not fit in 80 columns.
from app.report_content_gates import (  # noqa: F401
    _legacy_hypothesis_passes_safety_gate,
)
from app.report_content_gates import (
    _unverified_hypothesis_ids as _unverified_hypothesis_ids,
)
from app.report_content_gates import (
    _verified_hypothesis_count as _verified_hypothesis_count,
)

logger = logging.getLogger(__name__)


def _claim_evidence_ids(edge: dict[str, Any]) -> list[str]:
    """Evidence ids cited by one claim edge's supporting passages.

    A stored edge carries its provenance inside the ``supporting`` span
    objects (``{evidence_id, quote, ...}``), never as a flat ``evidence_id``
    column -- reading one off the edge itself silently yields nothing.
    """
    ids: list[str] = []
    for span in edge.get("supporting") or []:
        raw = span.get("evidence_id") if isinstance(span, dict) else None
        if raw:
            ids.append(str(raw))
    return ids


def _knowledge_base_topics(
    hypotheses: list[dict[str, Any]],
    claim_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build named technical topics from released hypotheses and claim links."""
    references_by_hypothesis: dict[str, list[str]] = {}
    for edge in claim_edges:
        if edge.get("label") not in ("supports", "partial"):
            continue
        hypothesis_id = str(edge.get("hypothesis_id") or "")
        references_by_hypothesis.setdefault(hypothesis_id, []).extend(
            _claim_evidence_ids(edge)
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


def _topic_reference_ids(
    raw: dict[str, Any], evidence_id_by_title: dict[str, str]
) -> list[str]:
    """Resolve a synthesized topic's cited titles to evidence ids."""
    references = raw.get("references") or []
    return sorted(
        {
            evidence_id_by_title.get(str(ref.get("title") or ""), "")
            for ref in references
            if isinstance(ref, dict)
        }
        - {""}
    )


def _synthesized_topic_from_raw(
    raw: Any, evidence_id_by_title: dict[str, str], fallback_index: int
) -> dict[str, Any] | None:
    """Build one synthesized topic, or ``None`` when unusable.

    A topic is unusable when it is not a dict, or none of its cited titles
    resolve to a durable evidence id.
    """
    if not isinstance(raw, dict):
        return None
    reference_ids = _topic_reference_ids(raw, evidence_id_by_title)
    if not reference_ids:
        return None
    return {
        "id": str(raw.get("id") or f"topic-{fallback_index}"),
        "title": str(raw.get("title") or "Technical topic"),
        "summary": str(raw.get("summary") or ""),
        "detail": str(raw.get("detail") or ""),
        "uncertainty": str(raw.get("uncertainty") or ""),
        "reference_ids": reference_ids,
    }


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
        topic = _synthesized_topic_from_raw(
            raw, evidence_id_by_title, len(topics) + 1
        )
        if topic is not None:
            topics.append(topic)
    return topics


def _contradicted_claims(claim_edges: list[dict[str, Any]]) -> list[str]:
    """Readable claim text for every edge the evidence contradicts.

    Textless edges are dropped rather than emitted blank: the Goal Report
    shows a section header whenever the list is non-empty, so a blank entry
    renders as a heading with nothing beneath it.
    """
    claims: list[str] = []
    for edge in claim_edges:
        if edge.get("label") != "contradicts":
            continue
        claim = str(edge.get("claim") or "").strip()
        if claim:
            claims.append(claim)
    return claims


def _recommended_direction(raw: Any) -> dict[str, Any]:
    """Normalize one meta-review strategic recommendation into named fields.

    The meta-review schema makes each recommendation an object of focus area,
    recommendation, and justification; stringifying it renders a raw object
    repr in the report. A bare string (from a provider that ignored the
    schema) becomes the recommendation with empty siblings.
    """
    if not isinstance(raw, dict):
        return {
            "focus_area": "",
            "recommendation": raw,
            "justification": "",
        }
    return {
        "focus_area": raw.get("focus_area") or "",
        "recommendation": raw.get("recommendation") or "",
        "justification": raw.get("justification") or "",
    }


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
        "contradictions": _contradicted_claims(claim_edges),
        "recommended_directions": [
            _recommended_direction(item)
            for item in meta.get("strategic_recommendations", [])
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
    """Map hypothesis id -> reasons its claims were not fully supported.

    A ``partial`` edge clears the reason like ``supports`` does: it credits
    relevant, consistent evidence, so it does not add an "unsupported" note
    that would contradict the hypothesis clearing the "Unverified" badge.
    """
    edge_reasons: dict[str, set[str]] = {}
    for edge in claim_edges:
        if edge.get("label") in ("supports", "partial") or (
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
    """Build the 'high_potential' idea bucket from the safe hypotheses.

    Every released idea, not the top few. The two buckets are a partition of
    the run's ideas -- ``non_viable`` is defined as everything *not* in this
    one -- and the UI shows both as counts side by side, so capping this
    half made the pair stop summing to the run's idea count as soon as a run
    released more than five ideas.
    """
    return [
        {
            "id": str(hypothesis.get("id")),
            "title": str(hypothesis.get("title") or "Untitled idea"),
            "reason": (
                "Released by safety and evidence gates and ranked by Elo."
            ),
        }
        for hypothesis in safe_hypotheses
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
    # is contradicted (an edge reason above), blocked by safety, set aside
    # during review, or deduplicated -- never for being merely unsupported
    # (those are published and badged "Unverified") and never for scoring
    # weakly (those rank and publish as "needs_revision").
    #
    # Review rejection and deduplication are reported apart. Merging them
    # told a scientist their idea had failed peer review when it had only
    # been folded into a higher-ranked idea saying the same thing.
    if reasons:
        return reasons
    if hypothesis.get("status") == "duplicate":
        reasons.append(
            "Folded into a higher-ranked idea that makes the same proposal."
        )
    elif hypothesis.get("status") == "rejected":
        reasons.append(
            "Set aside during review as scientifically unsound or not novel."
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


def _enrich_claim_span(
    raw_span: Any, sources: dict[str, dict[str, Any]]
) -> Any:
    """Attach source title/source/url metadata to one claim span.

    Non-dict spans are returned unchanged.
    """
    if not isinstance(raw_span, dict):
        return raw_span
    span = dict(raw_span)
    source = sources.get(str(span.get("evidence_id") or ""), {})
    span["source_title"] = str(
        span.get("source_title") or source.get("title") or ""
    )
    span["source"] = str(span.get("source") or source.get("source") or "")
    span["url"] = str(span.get("url") or source.get("url") or "")
    return span


def _enrich_claim_edge(
    edge: dict[str, Any], sources: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Enrich one claim edge's supporting/contradicting spans."""
    enriched = dict(edge)
    for key in ("supporting", "contradicting"):
        enriched[key] = [
            _enrich_claim_span(raw_span, sources)
            for raw_span in edge.get(key) or []
        ]
    return enriched


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
    return [
        _enrich_claim_edge(edge, sources)
        for edge in claim_edges
        if str(edge.get("hypothesis_id") or "") in released_ids
    ]
