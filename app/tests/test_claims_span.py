"""Locating an assessor's cited quote back to the passage it came from.

Production run bc77950f (2026-09-07/08, extended, free models) published
11 of 13 hypotheses "unverified": 156 of its 170 claim-evidence edges came
back ``insufficient`` and 8 of 13 hypotheses drew *zero* supported claims,
all-or-nothing per hypothesis -- and one hypothesis is one batched judging
call. The judge was not starved of evidence and was not silent: its
grounding calls carried 7137 prompt tokens each against the comparable
standard run's 6988, and answered with 3658 completion tokens against
3572. Same prompt, same evidence volume, same answer volume, an eighth of
the usable verdicts -- the difference being which model answered (the free
chain fell through to a second rung for every one of bc77950f's 13
grounding calls).

That is the signature of citations being *discarded* rather than never
made: a verdict whose cited spans cannot be located is downgraded to
INSUFFICIENT, and the resolution step required the assessor to echo a
36-character ``evidence_id`` back exactly -- the very "schemas must not
echo input back" anti-pattern ``claims_batch`` documents for claim text
but not for the evidence id. These tests pin the resolution being
tolerant of how a model actually cites (the prompt's own passage number
or an id stripped of its chunk suffix)
while keeping the anti-hallucination guarantee that the quote itself must
be verbatim in the cited evidence that was actually shown.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import pytest

from app.claims import (
    AssessorDraft,
    ClaimAssessment,
    EntailmentLabel,
    EvidencePassage,
    assess_claim,
    assess_claims_batch,
)
from app.claims_span import _locate_all

_PASSAGES = (
    EvidencePassage(
        evidence_id="7f1c9a20-1b2e-4f3a-9c8d-0a1b2c3d4e5f#0",
        text=(
            "Fasudil could down-regulate RhoA, GEF-H1, and phosphorylated "
            "GEF-H1 to inhibit ROCK signaling and further reduce Col I "
            "expression and the myofibroblast proportion."
        ),
        source="pubmed",
        url="https://example.org/fasudil",
    ),
    EvidencePassage(
        evidence_id="2b8e4d11-5c6f-4a7b-8d9e-1f2a3b4c5d6e#1",
        text=(
            "Verteporfin has been shown to effectively inhibit YAP-TEAD "
            "function in vivo in cardiac fibroblasts."
        ),
        source="web",
        url="https://example.org/verteporfin",
    ),
)

_CLAIM = "Fasudil reduces collagen I expression in cardiac fibroblasts."


def test_citation_by_passage_number_resolves() -> None:
    """A cited "1" is the passage number the prompt itself printed.

    ``claim_verifier._render_passages`` renders every passage as
    ``[1] evidence_id=<uuid>``, so a model citing the bracketed number it
    was shown is citing the passage correctly, not hallucinating.
    """
    spans = _locate_all(
        (("1", "reduce Col I expression and the myofibroblast proportion"),),
        _PASSAGES,
    )
    assert [s.evidence_id for s in spans] == [_PASSAGES[0].evidence_id]
    assert spans[0].source == "pubmed"


def test_numeric_evidence_id_cannot_shadow_a_passage_number() -> None:
    passages = (
        EvidencePassage("other", "The first passage has this claim quote."),
        EvidencePassage("1", "The second passage is unrelated."),
    )
    spans = _locate_all((("1", "claim quote"),), passages)
    assert [s.evidence_id for s in spans] == ["other"]


def test_internal_numeric_evidence_id_is_not_a_passage_number() -> None:
    passages = (
        EvidencePassage("other", "The first passage is unrelated."),
        EvidencePassage("1", "The second passage has this claim quote."),
    )
    spans = _locate_all(
        (("1", "claim quote"),), passages, cites_evidence_ids=True
    )
    assert [s.evidence_id for s in spans] == ["1"]


def test_out_of_range_number_cannot_resolve_as_an_evidence_id() -> None:
    passages = (EvidencePassage("99", "This quote is from another article."),)
    assert _locate_all((("99", "another article"),), passages) == []


def test_deterministic_assessment_keeps_numeric_evidence_id() -> None:
    passage = EvidencePassage(
        "12345", "Fasudil reduces collagen I expression in cardiac fibroblasts."
    )
    result = assess_claim(_CLAIM, [passage])
    assert result.label is EntailmentLabel.SUPPORTS
    assert [s.evidence_id for s in result.supporting_passages] == ["12345"]


def test_custom_assessor_keeps_numeric_evidence_id_by_default() -> None:
    passage = EvidencePassage(
        "12345", "Fasudil reduces collagen I expression in cardiac fibroblasts."
    )
    draft = AssessorDraft(
        EntailmentLabel.SUPPORTS,
        supporting=(("12345", "reduces collagen I expression"),),
    )
    result = assess_claim(
        _CLAIM, [passage], assessor=lambda _claim, _shown: draft
    )
    assert result.label is EntailmentLabel.SUPPORTS
    assert [s.evidence_id for s in result.supporting_passages] == ["12345"]


def test_batch_fallback_keeps_numeric_evidence_id() -> None:
    passage = EvidencePassage(
        "12345", "Fasudil reduces collagen I expression in cardiac fibroblasts."
    )
    result = assess_claims_batch(
        [_CLAIM],
        [passage],
        batch_assessor=lambda _claims, _shown: [None],
        assessor_id="llm:test",
    )[0]
    assert result.label is EntailmentLabel.SUPPORTS
    assert [s.evidence_id for s in result.supporting_passages] == ["12345"]


def test_internal_numeric_parent_id_resolves_later_chunk() -> None:
    passages = (
        EvidencePassage("12345#0", "First article chunk."),
        EvidencePassage("12345#1", "Later article chunk has the claim quote."),
    )
    spans = _locate_all(
        (("12345", "claim quote"),),
        passages,
        cites_evidence_ids=True,
    )
    assert [s.evidence_id for s in spans] == ["12345#1"]


def test_citation_dropping_the_chunk_suffix_resolves() -> None:
    """An id cited without its ``#<chunk>`` suffix still names its passage."""
    spans = _locate_all(
        (
            (
                "7f1c9a20-1b2e-4f3a-9c8d-0a1b2c3d4e5f",
                "inhibit ROCK signaling",
            ),
        ),
        _PASSAGES,
    )
    assert [s.evidence_id for s in spans] == [_PASSAGES[0].evidence_id]


def test_parent_id_resolves_quote_in_later_chunk() -> None:
    later = EvidencePassage(
        evidence_id="7f1c9a20-1b2e-4f3a-9c8d-0a1b2c3d4e5f#1",
        text="A later chunk describes a separate measured endpoint.",
    )
    spans = _locate_all(
        (
            (
                "7f1c9a20-1b2e-4f3a-9c8d-0a1b2c3d4e5f",
                "separate measured endpoint",
            ),
        ),
        (*_PASSAGES, later),
    )
    assert [s.evidence_id for s in spans] == [later.evidence_id]


def test_verbatim_quote_under_a_different_known_id_is_dropped() -> None:
    spans = _locate_all(
        ((_PASSAGES[0].evidence_id, "inhibit YAP-TEAD function in vivo"),),
        _PASSAGES,
    )
    assert spans == []


def test_verbatim_quote_under_an_unknown_id_is_dropped() -> None:
    spans = _locate_all(
        (("unrecognized-legacy-id", "inhibit YAP-TEAD function in vivo"),),
        _PASSAGES,
    )
    assert spans == []


def test_batch_unknown_key_cannot_borrow_another_shown_passage() -> None:
    passages = (
        EvidencePassage("ev-0", "Kinase X inhibition reduces tumor growth."),
        EvidencePassage("ev-1", "The response occurred in AML cell lines."),
    )
    draft = AssessorDraft(
        EntailmentLabel.SUPPORTS,
        supporting=(("99", "in AML cell lines"),),
        cites_evidence_ids=False,
    )
    results = assess_claims_batch(
        ["Kinase X inhibition reduces tumor growth."],
        passages,
        batch_assessor=lambda _claims, _shown: [draft],
        assessor_id="llm:test",
    )
    assert results[0].label is EntailmentLabel.INSUFFICIENT
    assert results[0].supporting_passages == ()


def test_quote_in_no_shown_passage_is_still_dropped() -> None:
    """The anti-hallucination guarantee is unchanged: no quote, no span."""
    assert (
        _locate_all(
            ((_PASSAGES[0].evidence_id, "olaparib cures cardiac fibrosis"),),
            _PASSAGES,
        )
        == []
    )


def test_dropped_citations_are_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A discarded citation is reported, not lost silently.

    The run this module documents could not be diagnosed from its own
    artifacts precisely because this loss left no trace.
    """
    with caplog.at_level(logging.WARNING, logger="app.claims_span"):
        _locate_all(
            (
                (_PASSAGES[0].evidence_id, "quote that is nowhere"),
                (_PASSAGES[0].evidence_id, "inhibit ROCK signaling"),
            ),
            _PASSAGES,
        )
    assert "1" in caplog.text
    assert "could not be located" in caplog.text


def test_batched_verdict_citing_by_number_keeps_its_label() -> None:
    """End to end: a by-number citation is not downgraded to insufficient."""

    def _by_number_assessor(
        claims: Sequence[str], passages: Sequence[EvidencePassage]
    ) -> Sequence[AssessorDraft | None]:
        return [
            AssessorDraft(
                label=EntailmentLabel.SUPPORTS,
                supporting=(("[1]", "reduce Col I expression"),),
                cites_evidence_ids=False,
            )
            for _ in claims
        ]

    results: list[ClaimAssessment] = assess_claims_batch(
        [_CLAIM],
        list(_PASSAGES),
        batch_assessor=_by_number_assessor,
        assessor_id="llm:test",
    )
    assert results[0].label is EntailmentLabel.SUPPORTS
    assert results[0].supporting_passages[0].evidence_id == (
        _PASSAGES[0].evidence_id
    )


def test_single_claim_verdict_citing_by_number_keeps_its_label() -> None:
    """The per-claim path resolves citations exactly as the batched one."""

    def _by_number_assessor(
        claim: str, passages: Sequence[EvidencePassage]
    ) -> AssessorDraft:
        return AssessorDraft(
            label=EntailmentLabel.PARTIAL,
            supporting=(("passage 1", "reduce Col I expression"),),
            cites_evidence_ids=False,
        )

    result = assess_claim(
        _CLAIM,
        list(_PASSAGES),
        assessor=_by_number_assessor,
        assessor_id="llm:test",
    )
    assert result.label is EntailmentLabel.PARTIAL
    assert result.supporting_passages[0].evidence_id == (
        _PASSAGES[0].evidence_id
    )
