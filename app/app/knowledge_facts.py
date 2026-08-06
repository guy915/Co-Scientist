"""Derive durable structured facts and contradictions (audit G14).

``claim_evidence`` (``app/store/schema.py``) is the only structured claim
table the store has, but its ``claim`` column is free text and its
``label`` a bare supports/contradicts/insufficient tag -- nothing
normalized or queryable as a "fact" or a "contradiction" on its own, and
the report's "Knowledge Base" section is re-synthesized from it on every
render rather than persisted. This module derives one durable row per
settled claim (``supports`` -> a fact, ``contradicts`` -> a contradiction;
``insufficient`` asserts nothing either way and is dropped), tagging each
with the biomedical entities its claim text mentions -- reusing the
engine's own entity extractor rather than a second implementation of the
same heuristic -- so the knowledge base is queryable by entity as well as
by hypothesis.

Kept explicitly per-run, never cross-run: FINDINGS.md records per-run
context memory as this product's faithful, verified behavior, and a
cross-run "Ideation Memory" as invented by the reference corpus with no
counterpart here. Every row this module builds carries only one run's own
claim_evidence.
"""

from __future__ import annotations

from typing import Any

from co_scientist.agents.reflection.reflection_entities import (
    extract_entity_names,
)

# Only these two labels assert something the knowledge base can hold as
# settled. "insufficient" means the evidence neither confirmed nor
# contradicted the claim, so it is not a fact and not a contradiction --
# there is nothing to carry over.
_KIND_BY_LABEL = {"supports": "fact", "contradicts": "contradiction"}

# Each label's corroborating evidence lives in a different span list on the
# edge (see app.report_content._claim_evidence_ids for the "supports" half
# of this same reasoning).
_SPAN_KEY_BY_LABEL = {"supports": "supporting", "contradicts": "contradicting"}

# A claim statement is denser than the single hypothesis title
# reflection_entities.extract_entity_names is tuned for (it typically names
# both a driver and what it acts on), so the cap is raised a little rather
# than reused verbatim.
_MAX_ENTITIES_PER_FACT = 5


def _span_evidence_ids(edge: dict[str, Any], span_key: str) -> list[str]:
    """Evidence ids cited by one claim edge's spans under ``span_key``."""
    ids: list[str] = []
    for span in edge.get(span_key) or []:
        raw = span.get("evidence_id") if isinstance(span, dict) else None
        if raw:
            ids.append(str(raw))
    return ids


def _fact_row(edge: dict[str, Any]) -> dict[str, Any] | None:
    """Build one durable fact/contradiction row from a claim-evidence edge.

    Args:
        edge: One row from ``store.list_claim_evidence``.

    Returns:
        A row ready for ``store.replace_knowledge_facts``, or None when the
        edge's label asserts nothing settled or carries no claim text.
    """
    label = str(edge.get("label") or "")
    kind = _KIND_BY_LABEL.get(label)
    if kind is None:
        return None
    statement = str(edge.get("claim") or "").strip()
    if not statement:
        return None
    evidence_ids = _span_evidence_ids(edge, _SPAN_KEY_BY_LABEL[label])
    return {
        "hypothesis_id": str(edge.get("hypothesis_id") or ""),
        "evidence_id": evidence_ids[0] if evidence_ids else None,
        "kind": kind,
        "statement": statement,
        "entities": extract_entity_names(
            statement, max_entities=_MAX_ENTITIES_PER_FACT
        ),
        "state": label,
    }


def derive_knowledge_facts(
    claim_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Derive durable fact/contradiction rows from a run's claim-evidence graph.

    Args:
        claim_edges: A run's *whole* claim-evidence graph (every hypothesis,
            not only the released ones) -- the knowledge base records what
            the run found, independent of what the published report shows,
            matching how ``report_content._contradicted_claims`` reads the
            same table.

    Returns:
        One row per settled (fact or contradiction) claim, in ``claim_edges``
        order.
    """
    rows = (_fact_row(edge) for edge in claim_edges)
    return [row for row in rows if row is not None]
