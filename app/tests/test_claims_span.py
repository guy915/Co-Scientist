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
tolerant of how a model actually cites (the prompt's own passage number,
an id stripped of its chunk suffix, or a right quote against a wrong id)
while keeping the anti-hallucination guarantee that the quote itself must
be verbatim in evidence that was actually shown.
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


def test_verbatim_quote_under_a_wrong_id_resolves_to_its_own_passage() -> None:
    """A right quote under a wrong id is a bookkeeping slip, not a fiction.

    The span is re-attributed to the passage that actually contains the
    quote, so the recorded provenance stays exact.
    """
    spans = _locate_all(
        ((_PASSAGES[0].evidence_id, "inhibit YAP-TEAD function in vivo"),),
        _PASSAGES,
    )
    assert [s.evidence_id for s in spans] == [_PASSAGES[1].evidence_id]
    assert spans[0].url == "https://example.org/verteporfin"


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
