"""Tests for durable structured fact/contradiction derivation (audit G14).

``derive_knowledge_facts`` is a pure function (no DB), tested directly here.
Store round-trip and the report-finalize wiring are covered in
``test_store_knowledge_facts.py``.
"""

from __future__ import annotations

from typing import Any

from app.knowledge_facts import derive_knowledge_facts


def _edge(
    label: str,
    claim: str = "IL-6 increases inflammation via STAT3 signaling.",
    **over: Any,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "hypothesis_id": "h1",
        "claim": claim,
        "label": label,
        "supporting": [],
        "contradicting": [],
    }
    base.update(over)
    return base


def test_supports_edge_becomes_a_fact() -> None:
    """A ``supports`` edge becomes a durable "fact" row."""
    facts = derive_knowledge_facts([_edge("supports")])
    assert len(facts) == 1
    assert facts[0]["kind"] == "fact"
    assert facts[0]["state"] == "supports"


def test_contradicts_edge_becomes_a_contradiction() -> None:
    """A ``contradicts`` edge becomes a durable "contradiction" row."""
    facts = derive_knowledge_facts([_edge("contradicts")])
    assert len(facts) == 1
    assert facts[0]["kind"] == "contradiction"
    assert facts[0]["state"] == "contradicts"


def test_insufficient_edge_is_dropped() -> None:
    """An insufficient edge asserts nothing and is not carried over."""
    facts = derive_knowledge_facts([_edge("insufficient")])
    assert facts == []


def test_edge_with_no_claim_text_is_dropped() -> None:
    """A settled edge with blank claim text produces no row either way."""
    facts = derive_knowledge_facts([_edge("supports", claim="  ")])
    assert facts == []


def test_fact_carries_the_statement_and_hypothesis() -> None:
    facts = derive_knowledge_facts(
        [_edge("supports", claim="TREM2 promotes microglial phagocytosis.")]
    )
    assert facts[0]["statement"] == "TREM2 promotes microglial phagocytosis."
    assert facts[0]["hypothesis_id"] == "h1"


def test_fact_extracts_entities_from_the_claim() -> None:
    """Entities mentioned in the claim text are tagged onto the row."""
    facts = derive_knowledge_facts(
        [_edge("supports", claim="TREM2 promotes microglial clearance.")]
    )
    assert "TREM2" in facts[0]["entities"]


def test_fact_evidence_id_comes_from_the_supporting_spans() -> None:
    """A fact's evidence id is read from supporting, not contradicting."""
    facts = derive_knowledge_facts(
        [
            _edge(
                "supports",
                supporting=[{"evidence_id": "ev-1"}],
                contradicting=[{"evidence_id": "ev-wrong"}],
            )
        ]
    )
    assert facts[0]["evidence_id"] == "ev-1"


def test_contradiction_evidence_id_comes_from_the_contradicting_spans() -> None:
    """A contradiction's evidence id is read from contradicting.

    Not from supporting -- the two labels' evidence lives in different span
    lists on the same edge.
    """
    facts = derive_knowledge_facts(
        [
            _edge(
                "contradicts",
                supporting=[{"evidence_id": "ev-wrong"}],
                contradicting=[{"evidence_id": "ev-2"}],
            )
        ]
    )
    assert facts[0]["evidence_id"] == "ev-2"


def test_fact_evidence_id_is_none_without_a_span() -> None:
    """A settled edge with no evidence-id span leaves evidence_id None."""
    facts = derive_knowledge_facts([_edge("supports")])
    assert facts[0]["evidence_id"] is None


def test_mixed_edges_only_keep_settled_ones() -> None:
    """A mixed batch keeps supports/contradicts, dropping insufficient."""
    edges = [
        _edge("supports", claim="A supports claim."),
        _edge("insufficient", claim="An insufficient claim."),
        _edge("contradicts", claim="A contradicts claim."),
    ]
    facts = derive_knowledge_facts(edges)
    assert [f["statement"] for f in facts] == [
        "A supports claim.",
        "A contradicts claim.",
    ]
