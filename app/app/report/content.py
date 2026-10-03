"""Report content derivation.

Holds the pure data-shaping helpers the report builder composes: knowledge-
base topic builders, agent-insight and idea-bucket derivation, and claim-
evidence enrichment. The exclusion filters (contradicted/unverified/unsafe)
live in ``report.gates``.
"""

from __future__ import annotations

import logging
from typing import Any

from co_scientist.agents.reflection.reflection_helpers import (
    extract_entity_names,
)

from app.claims.gate import (
    KNOWLEDGE_CONTRADICTION,
    KNOWLEDGE_FACT,
    is_categorical_contradiction,
    is_contradicting,
    is_excused,
    is_supporting,
    knowledge_kind,
)
from app.evidence_chunking import parent_evidence_id
from app.hypothesis.safety import is_blocking_status
from app.text_utils import (
    hypothesis_statement,
    hypothesis_title,
    readable_experiment_summary,
)

logger = logging.getLogger(__name__)


def _claim_evidence_ids(
    edge: dict[str, Any], span_key: str = "supporting"
) -> list[str]:
    """Evidence ids cited by one claim edge's selected passages.

    A stored edge carries its provenance inside the ``supporting`` span
    objects (``{evidence_id, quote, ...}``), never as a flat ``evidence_id``
    column -- reading one off the edge itself silently yields nothing.
    Resolved to the parent article id (``parent_evidence_id``): a span
    located inside a chunked passage carries the chunk's id, but every
    reader-facing reference here is keyed against the evidence table's own
    article-level id.
    """
    ids: list[str] = []
    for span in edge.get(span_key) or []:
        raw = span.get("evidence_id") if isinstance(span, dict) else None
        if raw:
            ids.append(parent_evidence_id(str(raw)))
    return ids


def _knowledge_base_topics(
    hypotheses: list[dict[str, Any]],
    claim_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build named technical topics from released hypotheses and claim links."""
    references_by_hypothesis: dict[str, list[str]] = {}
    for edge in claim_edges:
        if not is_supporting(edge):
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
                "detail": (
                    readable_experiment_summary(
                        str(hypothesis.get("experimental_context") or "")
                    )
                    or str(hypothesis.get("expected_effect") or "")
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
        # The theme this topic's subject heading sits under, when the run
        # funded the deep knowledge-base synthesis (F8). Empty for the
        # flat topics the research-overview call itself produces, which
        # the renderer prints exactly as it always did.
        "theme": str(raw.get("theme") or ""),
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


# What each contradiction entry says about its idea, chosen by the same
# predicate the release gate withholds on (``is_categorical_contradiction``),
# so the panel cannot claim a withholding the gate did not perform. A
# contradicted established-fact claim withholds its idea, which would
# otherwise read as a reference to an idea the reader cannot find; a
# contradicted proposal is a verdict on the idea and does not.
_WITHHELD_CONTRADICTION_NOTE = (
    "Contradicted by the evidence, so the idea proposing it was withheld "
    "from the ranked report."
)
_PROPOSAL_CONTRADICTION_NOTE = (
    "Contradicted by the evidence; this is the idea's own proposal, so the "
    "contradiction alone does not remove the idea from the report."
)


def _contradicted_claims(claim_edges: list[dict[str, Any]]) -> list[str]:
    """Readable claim text for every edge the evidence contradicts.

    Deliberately reads the run's *whole* edge list, not the released subset
    the rest of the report is scoped to. A contradicted categorical claim is
    exactly what makes ``_hypothesis_passes_safety_gate`` withhold its
    hypothesis, so the released edges carry none: scoping this to them would
    drop every withheld idea's entry, emptying the panel of its main content
    while looking like a consistency fix.

    Keeping the edges therefore means a categorical entry names a claim of an
    idea the reader will not find in the report, which read as a dangling
    reference. Each such entry carries ``_WITHHELD_CONTRADICTION_NOTE``, which
    says so: the evidence against an idea is the run's finding and worth
    reporting, and the idea's absence is a fact about it, not an omission. A
    contradicted *proposal* is listed too (``claims.verdict.is_contradicting``
    ignores the role) but its idea is not withheld for it, so it carries
    ``_PROPOSAL_CONTRADICTION_NOTE`` instead of claiming a withholding.

    Textless edges are dropped rather than emitted blank: the Goal Report
    shows a section header whenever the list is non-empty, so a blank entry
    renders as a heading with nothing beneath it.
    """
    claims: list[str] = []
    for edge in claim_edges:
        if not is_contradicting(edge):
            continue
        claim = str(edge.get("claim") or "").strip()
        if claim:
            note = (
                _WITHHELD_CONTRADICTION_NOTE
                if is_categorical_contradiction(edge)
                else _PROPOSAL_CONTRADICTION_NOTE
            )
            claims.append(f"{claim} ({note})")
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


def _key_findings(hypotheses: list[dict[str, Any]]) -> list[str]:
    """The leading ideas' proposals, labelled as the panel presents them.

    Resolved through ``hypothesis_statement`` -- the same helper the markdown
    body's "Proposed hypothesis" line uses -- so one report cannot quote the
    same idea two ways. An idea with no proposal text is left out rather than
    emitted as a bare label, matching the markdown entry, which omits the
    line entirely; the frontend drops blank strings but would happily render
    a bullet reading only "Proposed hypothesis:".

    Args:
        hypotheses: The released hypotheses, best-ranked first.

    Returns:
        One labelled finding per idea among the leading five that has a
        proposal to show.
    """
    statements = (hypothesis_statement(h) for h in hypotheses[:5])
    return [
        f"Proposed hypothesis: {statement}"
        for statement in statements
        if statement
    ]


def _agent_insights(
    hypotheses: list[dict[str, Any]],
    claim_edges: list[dict[str, Any]],
    meta_review: dict[str, Any] | None,
) -> dict[str, Any]:
    """Derive visible findings, uncertainty, contradictions, and experiments.

    ``hypotheses`` is the released set, so findings and experiments describe
    only ideas the report carries. ``claim_edges`` is the run's whole edge
    list on purpose -- see :func:`_contradicted_claims` for why scoping it to
    the released edges would drop the withheld ideas' contradictions rather
    than tidy the panel.
    """
    meta = meta_review or {}
    return {
        "key_findings": _key_findings(hypotheses),
        "uncertainties": [
            str(item) for item in meta.get("common_weaknesses", [])
        ],
        "contradictions": _contradicted_claims(claim_edges),
        "recommended_directions": [
            _recommended_direction(item)
            for item in meta.get("strategic_recommendations", [])
        ],
        "next_experiments": [
            summary
            for hypothesis in hypotheses[:5]
            if (
                summary := readable_experiment_summary(
                    str(hypothesis.get("experimental_context") or "")
                )
            )
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
        if is_supporting(edge) or is_excused(edge):
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

    Titles come from ``hypothesis_title`` so a bucket names an idea exactly
    as the markdown body, the event stream, and the leaderboard do; naming it
    here instead left a hypothesis carrying only ``text`` reading "Untitled
    idea" in the buckets and correctly everywhere else in the same report.
    """
    return [
        {
            "id": str(hypothesis.get("id")),
            "title": hypothesis_title(hypothesis),
            "reason": (
                "Released by safety and evidence gates and ranked by Elo."
            ),
        }
        for hypothesis in safe_hypotheses
    ]


def _non_viable_reasons(
    hypothesis: dict[str, Any], edge_reasons: dict[str, set[str]]
) -> list[str]:
    """Return the excluded-idea reasons for one non-viable hypothesis.

    Checks status first, then a contradicting claim, then a blocking
    safety status -- the same precedence
    ``_hypothesis_passes_safety_gate`` uses to decide exclusion in the
    first place (see ``_exclusion_cause``, its analogous classifier for
    the run-level blocked reason). An idea that is both status-rejected
    and contradicted was excluded by the gate for its status, since the
    gate never reaches the contradiction check for it; reporting evidence
    or safety ahead of status here made the per-idea reason and the
    run's blocked reason name two different causes for the very same
    exclusion.

    Review rejection and deduplication are reported apart. Merging them
    told a scientist their idea had failed peer review when it had only
    been folded into a higher-ranked idea saying the same thing.
    """
    if hypothesis.get("status") == "duplicate":
        return [
            "Folded into a higher-ranked idea that makes the same proposal."
        ]
    if hypothesis.get("status") == "rejected":
        return [
            "Set aside during review: the reviewer judged it scientifically"
            " unsound or already established (a reviewer's own judgment,"
            " not a literature search)."
        ]
    # Under rank-and-publish an idea only leaves the ranked report when it
    # is contradicted (an edge reason below), blocked by safety, set aside
    # during review, or deduplicated -- never for being merely unsupported
    # (those are published and badged "Unverified") and never for scoring
    # weakly (those rank and publish as "needs_revision").
    hypothesis_id = str(hypothesis.get("id"))
    reasons = sorted(edge_reasons.get(hypothesis_id, set()))
    if is_blocking_status(str(hypothesis.get("safety_status") or "")):
        reasons.append("The scientific safety review blocked this idea.")
    return reasons


def _non_viable_bucket(
    all_hypotheses: list[dict[str, Any]],
    safe_ids: set[str],
    edge_reasons: dict[str, set[str]],
) -> list[dict[str, Any]]:
    """Build the 'non_viable' idea bucket for every excluded hypothesis.

    Titles come from ``hypothesis_title`` for the same reason as in
    :func:`_high_potential_bucket`: one naming rule across the whole report.
    """
    non_viable = []
    for hypothesis in all_hypotheses:
        hypothesis_id = str(hypothesis.get("id"))
        if hypothesis_id in safe_ids:
            continue
        reasons = _non_viable_reasons(hypothesis, edge_reasons)
        non_viable.append(
            {
                "id": hypothesis_id,
                "title": hypothesis_title(hypothesis),
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
    source = sources.get(
        parent_evidence_id(str(span.get("evidence_id") or "")), {}
    )
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


def released_claim_evidence(
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


def format_deep_verification_critique(
    probes: list[dict[str, Any]], verdict: str | None
) -> tuple[str, str]:
    """Render deep-verification probes into persisted summary and critique."""
    summary = f"Deep verification verdict: {verdict or 'unspecified'}"
    lines = [summary, ""]
    for idx, probe in enumerate(probes, start=1):
        flag = (
            "fundamental"
            if probe.get("assumption_is_fundamental")
            else "non-fundamental"
        )
        lines.append(f"Probe {idx} ({flag} assumption):")
        for label, key in (
            ("Question", "question"),
            ("Answer", "answer"),
            ("Reasoning", "reasoning"),
        ):
            value = str(probe.get(key, "")).strip()
            if value:
                lines.append(f"  {label}: {value}")
        lines.append("")
    return summary, "\n".join(lines).strip()


# Each kind's corroborating evidence lives in a different span list on the
# edge (see app.report.content._claim_evidence_ids for the "supports" half
# of this same reasoning). Which edges are a kind at all -- only ``supports``
# and ``contradicts``, never ``partial`` or ``insufficient``, which assert
# nothing settled -- is ``claims.gate.knowledge_kind``.
_SPAN_KEY_BY_KIND = {
    KNOWLEDGE_FACT: "supporting",
    KNOWLEDGE_CONTRADICTION: "contradicting",
}

# A claim statement is denser than the single hypothesis title
# reflection_entities.extract_entity_names is tuned for (it typically names
# both a driver and what it acts on), so the cap is raised a little rather
# than reused verbatim.
_MAX_ENTITIES_PER_FACT = 5


def _fact_row(edge: dict[str, Any]) -> dict[str, Any] | None:
    """Build one durable fact/contradiction row from a claim-evidence edge.

    Args:
        edge: One row from ``store.list_claim_evidence``.

    Returns:
        A row ready for ``store.replace_knowledge_facts``, or None when the
        edge's label asserts nothing settled or carries no claim text.
    """
    kind = knowledge_kind(edge)
    if kind is None:
        return None
    statement = str(edge.get("claim") or "").strip()
    if not statement:
        return None
    evidence_ids = _claim_evidence_ids(edge, _SPAN_KEY_BY_KIND[kind])
    return {
        "hypothesis_id": str(edge.get("hypothesis_id") or ""),
        "evidence_id": evidence_ids[0] if evidence_ids else None,
        "kind": kind,
        "statement": statement,
        "entities": extract_entity_names(
            statement, max_entities=_MAX_ENTITIES_PER_FACT
        ),
        "state": str(edge["label"]),
    }


def derive_knowledge_facts(
    claim_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Derive durable fact/contradiction rows from a run's claim-evidence graph.

    Args:
        claim_edges: A run's *whole* claim-evidence graph (every hypothesis,
            not only the released ones) -- the knowledge base records what
            the run found, independent of what the published report shows,
            matching how ``report.content._contradicted_claims`` reads the
            same table.

    Returns:
        One row per settled (fact or contradiction) claim, in ``claim_edges``
        order.
    """
    rows = (_fact_row(edge) for edge in claim_edges)
    return [row for row in rows if row is not None]
