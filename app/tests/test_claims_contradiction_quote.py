"""The deterministic assessor may only contradict with a negating quote.

Regression fixtures are real production data: standard run e47a3ba1
(2026-09-08) persisted 11 ``contradicts`` claim-evidence edges out of 101,
every one of them stamped ``llm:openrouter/minimax/minimax-m3:free`` and
*none* of them produced by the LLM judge -- the entailment call failed (or
came back unparseable) and both entry points fall back to
``deterministic_assessor`` while keeping the ``llm:`` provenance, so the
founded-contradiction guard in ``claim_verifier`` never saw them.

The deterministic assessor tested the contradiction marker against the whole
passage and then cited ``_best_sentence`` -- the sentence stating the most of
the claim, i.e. the one *least* likely to be the negation. Measured over
those 11 edges: zero cited quotes contained any
``claims_assessor._CONTRADICTION_MARKERS`` entry, and 10 of 11 also fell
below the 0.25 subject-coverage bar (max 0.30).

The three claim/quote pairs below are verbatim from that run.
"""

# Fixtures are verbatim production text: the Greek letters in the protein
# names below are part of the data and must not be transliterated.
# ruff: noqa: RUF001

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.claims import (
    EntailmentLabel,
    EvidencePassage,
    assess_claim,
    assess_claims_batch,
    deterministic_assessor,
)
from app.claims_assessor import _CONTRADICTION_MARKERS

# A negation elsewhere in the same abstract -- routine reporting boilerplate,
# and what used to make the whole passage read as contradicting whatever
# sentence was cited from it.
_UNRELATED_NEGATION = "Body weight did not differ between groups."


def _passage(*sentences: str) -> EvidencePassage:
    return EvidencePassage(
        evidence_id="e1",
        text=" ".join(sentences),
        source="pubmed",
        url="https://example.org/1",
    )


def _quotes(spans: Sequence[object]) -> list[str]:
    return [getattr(span, "quote", "") for span in spans]


def _carries_a_marker(quote: str) -> bool:
    lowered = quote.lower()
    return any(marker in lowered for marker in _CONTRADICTION_MARKERS)


# --- e47a3ba1, edge 3: a confirmatory quote labelled a contradiction --------

_REDUCTION_CLAIM = (
    "Together, these actions reduce collagen synthesis and α-SMA "
    "expression, attenuating the fibrotic phenotype."
)
# Verbatim from the run: it states the claim's own direction.
_REDUCTION_QUOTE = (
    "Treatment with LGK-974 significantly reduced both α-SMA and "
    "collagen type I expression, whereas ETC-159 selectively decreased "
    "collagen type I."
)


def test_confirmatory_quote_is_not_a_contradiction() -> None:
    passage = _passage(
        "Wnt inhibition and the fibrotic phenotype in cardiac fibroblasts.",
        _REDUCTION_QUOTE,
        _UNRELATED_NEGATION,
    )
    result = assess_claim(_REDUCTION_CLAIM, [passage])
    assert result.label is not EntailmentLabel.CONTRADICTS
    assert _REDUCTION_QUOTE not in _quotes(result.contradicting_passages)


# --- e47a3ba1, edge 1: a quote about a different drug entirely --------------

_METFORMIN_CLAIM = (
    "Metformin activates AMPK in human cardiac fibroblasts, leading to "
    "inhibitory phosphorylation of Smad3 (Ser203/207) and suppression of "
    "HIF-1α-mediated glycolysis, thereby blocking TGF-β-induced "
    "myofibroblast transition and collagen deposition."
)
_PIRFENIDONE_QUOTE = (
    "Furthermore, pirfenidone attenuated TGF-β1- and CTHRC1-induced "
    "fibroblast activity, upregulation of bone morphogenic protein-4"
    "(BMP-4)/Gremlin1, and downregulation of α-smooth muscle actin, "
    "fibronectin, and FHL2, similar to that observed post-CTHRC1 inhibition."
)


def test_off_drug_quote_is_not_a_contradiction() -> None:
    # The abstract is padded with the on-topic sentences a real one carries,
    # so the passage clears the contradiction branch's own
    # ``support_threshold / 2`` bar (0.571 coverage, against 0.048 for the
    # cited sentences alone). Without that the old whole-passage marker
    # test never fired here and the fixture would pass either way.
    passage = _passage(
        "Pirfenidone attenuates lung fibrotic fibroblast responses to "
        "transforming growth factor-β1.",
        _PIRFENIDONE_QUOTE,
        "Myofibroblast transition and collagen deposition were assessed in "
        "human cardiac fibroblasts after TGF-β1 stimulation.",
        "AMPK phosphorylation, Smad3 phosphorylation and glycolysis were "
        "measured; HIF-1α protein was quantified.",
        _UNRELATED_NEGATION,
    )
    result = assess_claim(_METFORMIN_CLAIM, [passage])
    assert result.label is not EntailmentLabel.CONTRADICTS
    assert _PIRFENIDONE_QUOTE not in _quotes(result.contradicting_passages)


# --- e47a3ba1, edge 2: a quote about a different stimulus -------------------

_AMPK_CLAIM = (
    "Metformin enters cardiac fibroblasts and activates AMPK via LKB1."
)
_GLUCOSE_QUOTE = (
    "We found that glucose starvation transiently activates AMPK, whereas "
    "changes in glucagon and insulin levels had no impact on AMPK."
)


def test_off_stimulus_quote_is_not_a_contradiction() -> None:
    passage = _passage(
        "AMPK activation in fibroblasts under nutrient stress.",
        _GLUCOSE_QUOTE,
        _UNRELATED_NEGATION,
    )
    result = assess_claim(_AMPK_CLAIM, [passage])
    assert result.label is not EntailmentLabel.CONTRADICTS
    assert _GLUCOSE_QUOTE not in _quotes(result.contradicting_passages)


# --- A real opposing quote must still be believed ---------------------------

_ON_SUBJECT_NEGATION = (
    "Metformin did not reduce collagen I expression in human cardiac "
    "fibroblasts."
)


def test_on_subject_negation_still_contradicts() -> None:
    """The genuine case: the negation is about the claim's own subject."""
    claim = (
        "Metformin reduces collagen I expression in human cardiac fibroblasts."
    )
    passage = _passage(
        "Metformin and collagen I expression in human cardiac fibroblasts.",
        "Cells were treated for 48 hours.",
        _ON_SUBJECT_NEGATION,
    )
    result = assess_claim(claim, [passage])
    assert result.label is EntailmentLabel.CONTRADICTS
    assert _ON_SUBJECT_NEGATION in _quotes(result.contradicting_passages)


def test_cited_contradiction_quote_carries_the_negation() -> None:
    """The quote shown to a reader is the sentence that actually negates.

    The passage's *best-matching* sentence restates the claim; only the
    later sentence negates it. Citing the former (which is what the
    whole-passage marker test used to do) shows a reader a quote that
    reads as agreement under a CONTRADICTS verdict.
    """
    claim = (
        "Metformin reduces collagen I expression in human cardiac fibroblasts."
    )
    passage = _passage(
        "Metformin reduces collagen I expression in human cardiac "
        "fibroblasts, we hypothesized.",
        _ON_SUBJECT_NEGATION,
    )
    draft = deterministic_assessor(claim, [passage])
    assert draft.label is EntailmentLabel.CONTRADICTS
    for _, quote in draft.contradicting:
        assert _carries_a_marker(quote)


def test_llm_assessor_fallback_cannot_yield_an_unfounded_contradiction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production path of run e47a3ba1, end to end.

    ``make_llm_assessor`` falls back to the deterministic assessor on any
    provider/parse failure while keeping its ``llm:<model>`` provenance,
    which is why the run's edges looked like LLM verdicts. That fallback
    draft must be founded too.
    """
    from app import claim_verifier

    monkeypatch.setattr(
        claim_verifier, "_call_llm_entailment", lambda *a, **k: None
    )
    assessor, assessor_id = claim_verifier.make_llm_assessor("m")
    passage = _passage(
        "Wnt inhibition and the fibrotic phenotype in cardiac fibroblasts.",
        _REDUCTION_QUOTE,
        _UNRELATED_NEGATION,
    )
    draft = assessor(_REDUCTION_CLAIM, [passage])
    assert assessor_id == "llm:m"
    assert draft.label is not EntailmentLabel.CONTRADICTS


def test_batch_fallback_cannot_yield_an_unfounded_contradiction() -> None:
    """The route run e47a3ba1 actually took: the batched assessor.

    Its provider failures are what the run logged
    (``app.claim_verifier_batch``); a batch that returns no usable draft
    for a claim falls that claim back to the deterministic assessor
    (``claims_batch._fallback_assessment``), again under the batch's own
    ``llm:<model>`` provenance.
    """
    passage = _passage(
        "Wnt inhibition and the fibrotic phenotype in cardiac fibroblasts.",
        _REDUCTION_QUOTE,
        _UNRELATED_NEGATION,
    )
    (result,) = assess_claims_batch(
        [_REDUCTION_CLAIM],
        [passage],
        batch_assessor=lambda claims, _: [None] * len(claims),
        assessor_id="llm:m",
    )
    assert result.assessor == "llm:m"
    assert result.label is not EntailmentLabel.CONTRADICTS
    assert _REDUCTION_QUOTE not in _quotes(result.contradicting_passages)
