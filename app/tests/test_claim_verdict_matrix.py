"""Pin how each site reads a claim-evidence edge: the label x role matrix.

The persisted edge's ``label`` (supports / partial / contradicts /
insufficient) and ``claim_role`` (categorical / speculative) are read at many
sites, each asking a slightly different question. The answers are *not* all the
same rule, and the differences are deliberate:

* ``partial`` counts as supported for the report's "Unverified" badge and the
  claim gate, but is *not* a durable knowledge-base fact.
* ``contradicts`` + ``speculative`` does not withhold an idea from the report,
  yet the withheld-contradiction panel and the knowledge base still list it.
* A missing label reads as ``insufficient`` for the reader-facing status text
  but is *not* excused by a speculative role in the unsupported-reasons check.

This table was written against the sites' string comparisons and is kept
unchanged across the refactor that moved them behind ``app.claim_verdict``;
a change to any cell is a change in published behavior.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.claim_grounding import _has_supported_claim
from app.claims_gate import ClaimAssessment, EntailmentLabel
from app.claims_gate import _blocks_for_missing_support as blocks_for_missing
from app.claims_span import _downgrade_unproven_label
from app.knowledge_facts import derive_knowledge_facts
from app.report import content as report_content
from app.report import gates as report_gates
from app.report.markdown.hypothesis import _claim_status
from app.store import NewClaimEvidence

_LABELS = ("supports", "partial", "contradicts", "insufficient", None)
_ROLES = ("categorical", "speculative", None)
# Values no writer produces; the sites must degrade, not raise.
_ODD = (("bogus", "categorical"), ("insufficient", "exotic"))

_SUPPORTED = {"supports", "partial"}
_REASON = "Evidence verification did not support every material claim."
_STATUS = {
    "supports": "Supported",
    "partial": "Partially supported",
    "contradicts": "Contradicted",
}
_UNEXCUSED_STATUS = "Unsupported categorical claim"
_EXCUSED_STATUS = "Speculative — evidence insufficient"


def _edge(label: str | None, role: str | None) -> dict[str, Any]:
    edge: dict[str, Any] = {
        "hypothesis_id": "h1",
        "claim": "IL-6 increases inflammation via STAT3 signaling.",
        "supporting": [{"evidence_id": "e-for", "quote": "q"}],
        "contradicting": [{"evidence_id": "e-against", "quote": "q"}],
    }
    if label is not None:
        edge["label"] = label
    if role is not None:
        edge["claim_role"] = role
    return edge


def _cases() -> list[tuple[str | None, str | None]]:
    grid = [(label, role) for label in _LABELS for role in _ROLES]
    return grid + list(_ODD)


def _speculative(role: str | None) -> bool:
    return role == "speculative"


@pytest.mark.parametrize(("label", "role"), _cases())
def test_supported_means_supports_or_partial(label: Any, role: Any) -> None:
    ids = report_gates._supported_hypothesis_ids([_edge(label, role)])
    assert ids == ({"h1"} if label in _SUPPORTED else set())


@pytest.mark.parametrize(("label", "role"), _cases())
def test_a_contradiction_withholds_only_when_categorical(
    label: Any, role: Any
) -> None:
    ids = report_gates._contradicted_hypothesis_ids(
        "", None, claim_edges=[_edge(label, role)]
    )
    expected = label == "contradicts" and not _speculative(role)
    assert ids == ({"h1"} if expected else set())


@pytest.mark.parametrize(("label", "role"), _cases())
def test_the_withheld_contradiction_panel_ignores_role(
    label: Any, role: Any
) -> None:
    claims = report_content._contradicted_claims([_edge(label, role)])
    assert len(claims) == (1 if label == "contradicts" else 0)


@pytest.mark.parametrize(("label", "role"), _cases())
def test_unsupported_reason_skips_support_and_excused_gaps(
    label: Any, role: Any
) -> None:
    reasons = report_content._claim_edge_reasons([_edge(label, role)])
    excused = label == "insufficient" and _speculative(role)
    clean = label in _SUPPORTED or excused
    assert reasons == ({} if clean else {"h1": {_REASON}})


@pytest.mark.parametrize(("label", "role"), _cases())
def test_reader_facing_status_text(label: Any, role: Any) -> None:
    if label in _STATUS:
        expected = _STATUS[label]
    elif _speculative(role):
        expected = _EXCUSED_STATUS
    else:
        expected = _UNEXCUSED_STATUS
    assert _claim_status(_edge(label, role)) == expected


@pytest.mark.parametrize(("label", "role"), _cases())
def test_knowledge_base_topic_cites_only_supporting_edges(
    label: Any, role: Any
) -> None:
    topics = report_content._knowledge_base_topics(
        [{"id": "h1", "title": "T"}], [_edge(label, role)]
    )
    expected = ["e-for"] if label in _SUPPORTED else []
    assert topics[0]["reference_ids"] == expected


@pytest.mark.parametrize(("label", "role"), _cases())
def test_only_settled_claims_become_knowledge_rows(
    label: Any, role: Any
) -> None:
    rows = derive_knowledge_facts([_edge(label, role)])
    got = [(r["kind"], r["state"], r["evidence_id"]) for r in rows]
    expected = {
        "supports": [("fact", "supports", "e-for")],
        "contradicts": [("contradiction", "contradicts", "e-against")],
    }
    assert got == expected.get(label, [])


def _assessment(label: EntailmentLabel) -> ClaimAssessment:
    return ClaimAssessment("claim", label, (), (), "test")


@pytest.mark.parametrize("label", list(EntailmentLabel))
def test_the_claim_gate_counts_partial_as_support(
    label: EntailmentLabel,
) -> None:
    assessments = [_assessment(label)]
    supported = label.value in _SUPPORTED
    assert _has_supported_claim([(assessments[0], "categorical")]) is supported
    blocks = blocks_for_missing(assessments, require_supported_claim=True)
    assert blocks is not supported
    assert not blocks_for_missing(assessments, require_supported_claim=False)


@pytest.mark.parametrize("label", list(EntailmentLabel))
def test_an_unproven_verdict_downgrades_to_insufficient(
    label: EntailmentLabel,
) -> None:
    span: Any = object()
    insufficient = EntailmentLabel.INSUFFICIENT
    proven_for = _downgrade_unproven_label(label, [span], [])
    proven_against = _downgrade_unproven_label(label, [], [span])
    contradicts = label is EntailmentLabel.CONTRADICTS
    assert proven_for is (insufficient if contradicts else label)
    assert proven_against is (
        label if contradicts or label is insufficient else insufficient
    )
    assert _downgrade_unproven_label(label, [], []) is insufficient


def test_a_persisted_edge_defaults_to_a_categorical_claim() -> None:
    edge = NewClaimEvidence("r", "h", "c", "supports", [], [], "a")
    assert edge.claim_role == "categorical"
