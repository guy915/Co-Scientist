"""Short scientific terms must reach assessment without implying entailment."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.claims import (
    AssessorDraft,
    EntailmentLabel,
    EvidencePassage,
    as_passages,
    assess_claim,
)


@pytest.mark.parametrize(
    "claim, passage",
    [
        ("p53 inhibits cancer invasion.", "p53 curbs cellular migration."),
        (
            "DNA contains hereditary information.",
            "DNA encodes inherited instructions.",
        ),
        (
            "Protein H folds cooperatively.",
            "H adopts native structure through a concerted transition.",
        ),
        ("Locus J/K predicts trait Z.", "J and K cosegregate with Z."),
    ],
)
def test_short_identifier_passage_reaches_semantic_assessment(
    claim: str,
    passage: str,
) -> None:
    seen: list[EvidencePassage] = []

    def assess(
        _claim: str, passages: Sequence[EvidencePassage]
    ) -> AssessorDraft:
        seen.extend(passages)
        return AssessorDraft(EntailmentLabel.INSUFFICIENT)

    result = assess_claim(claim, as_passages([passage]), assessor=assess)
    assert [p.text for p in seen] == [passage]
    assert result.label is EntailmentLabel.INSUFFICIENT


def test_identifier_only_overlap_does_not_establish_support() -> None:
    result = assess_claim(
        "p53 inhibits cancer invasion.",
        as_passages(["p53 curbs cellular migration."]),
    )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()
    assert result.contradicting_passages == ()


def test_shared_function_words_do_not_admit_unrelated_evidence() -> None:
    from app.claims import retrieve_passages

    assert (
        retrieve_passages(
            "The cat sat on a rug.",
            as_passages(["The jet flew on a sunny day."]),
        )
        == []
    )


def test_short_term_retrieval_keeps_rank_limit_and_stable_ties() -> None:
    from app.claims import retrieve_passages

    passages = as_passages(
        [
            "DNA encodes inherited instructions.",
            "DNA supplies cellular blueprints.",
            "DNA contains hereditary information.",
        ]
    )
    ranked = retrieve_passages(
        "DNA contains hereditary information.", passages, top_k=2
    )
    assert [p.evidence_id for p in ranked] == ["passage-2", "passage-0"]
    assert (
        retrieve_passages(
            "DNA contains hereditary information.", passages, top_k=0
        )
        == []
    )


def test_new_identifier_evidence_invalidates_reused_assessment() -> None:
    from app.claims.freshness import ClaimRecord, claim_fingerprint

    claim = ClaimRecord("Protein H folds cooperatively.", "categorical")
    empty = claim_fingerprint(claim, [], "llm:test")
    unrelated = as_passages(["Ocean salinity varies seasonally."])
    assert claim_fingerprint(claim, unrelated, "llm:test") == empty
    relevant = EvidencePassage(
        "protein-study",
        "H adopts native structure through a concerted transition.",
    )
    assert claim_fingerprint(claim, [*unrelated, relevant], "llm:test") != empty


def test_long_function_words_do_not_supply_retrieval_overlap() -> None:
    from app.claims import retrieve_passages

    assert (
        retrieve_passages(
            "This protein folds with cooperative kinetics.",
            as_passages(["This ocean circulates with seasonal currents."]),
        )
        == []
    )
