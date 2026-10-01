"""The claim-verdict interface over a persisted claim-evidence edge.

``test_claim_verdict_matrix.py`` pins what each reader of the edge answers;
this file pins the interface they now share, including how it degrades on
legacy edges (no label, no role, an unrecognized value).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.claim_verdict import (
    DEFAULT_CLAIM_ROLE,
    ClaimRole,
    claim_status,
    is_categorical_contradiction,
    is_contradicting,
    is_excused,
    is_speculative,
    is_supporting,
    knowledge_kind,
    label_of,
    role_of,
)
from app.claims_gate import EntailmentLabel


def _edge(**fields: Any) -> dict[str, Any]:
    return dict(fields)


def test_the_persisted_vocabulary_is_unchanged() -> None:
    assert [label.value for label in EntailmentLabel] == [
        "supports",
        "partial",
        "contradicts",
        "insufficient",
    ]
    assert [role.value for role in ClaimRole] == ["categorical", "speculative"]
    assert DEFAULT_CLAIM_ROLE == "categorical"


@pytest.mark.parametrize("raw", [None, "", "bogus", "Supports", 3])
def test_a_missing_or_unrecognized_label_has_no_verdict(raw: Any) -> None:
    edge = _edge(label=raw)
    assert label_of(edge) is None
    assert not is_supporting(edge)
    assert not is_contradicting(edge)
    assert knowledge_kind(edge) is None


def test_a_missing_role_reads_as_categorical() -> None:
    assert role_of(_edge()) == "categorical"
    assert role_of(_edge(claim_role="")) == "categorical"
    assert role_of(_edge(claim_role="speculative")) == "speculative"
    assert role_of(_edge(claim_role="exotic")) == "exotic"
    assert is_speculative("speculative")
    assert not is_speculative(None) and not is_speculative("exotic")


def test_only_supports_and_partial_are_supporting() -> None:
    got = {label.value: label.is_supporting for label in EntailmentLabel}
    assert got == {
        "supports": True,
        "partial": True,
        "contradicts": False,
        "insufficient": False,
    }
    assert is_supporting(_edge(label="partial"))
    assert not is_supporting(_edge(label="insufficient"))


def test_a_proposal_can_be_contradicted_without_withholding_the_idea() -> None:
    for role in ("categorical", None):
        edge = _edge(label="contradicts", claim_role=role)
        assert is_contradicting(edge) and is_categorical_contradiction(edge)
    proposal = _edge(label="contradicts", claim_role="speculative")
    assert is_contradicting(proposal)
    assert not is_categorical_contradiction(proposal)


def test_only_an_explicit_insufficient_proposal_is_excused() -> None:
    assert is_excused(_edge(label="insufficient", claim_role="speculative"))
    assert not is_excused(_edge(label="insufficient"))
    assert not is_excused(_edge(claim_role="speculative"))
    assert not is_excused(_edge(label="contradicts", claim_role="speculative"))


def test_partial_is_not_a_knowledge_row() -> None:
    kinds = {
        label.value: knowledge_kind(_edge(label=label.value))
        for label in EntailmentLabel
    }
    assert kinds == {
        "supports": "fact",
        "partial": None,
        "contradicts": "contradiction",
        "insufficient": None,
    }


def test_status_reads_a_missing_label_as_insufficient() -> None:
    assert claim_status(_edge(label="partial")) == "Partially supported"
    assert claim_status(_edge(claim_role="speculative")) == (
        "Speculative — evidence insufficient"
    )
    assert claim_status(_edge()) == "Unsupported categorical claim"
