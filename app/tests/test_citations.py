"""Citation classifier covers all four states."""

from __future__ import annotations

import pytest

from app.citations import (
    ALL_STATES,
    CitationRecord,
    _token_overlap,
    classify_citation,
)


def test_states_are_exactly_four() -> None:
    assert set(ALL_STATES) == {
        "verified",
        "partial",
        "unsupported",
        "unavailable",
    }


@pytest.mark.parametrize(
    ("url", "abstract", "claim", "available", "expected"),
    [
        ("", "anything", "anything", True, "unavailable"),
        ("https://example.org", "anything", "anything", False, "unavailable"),
        (
            "https://example.org/1",
            "mitochondrial biogenesis brown adipose thermogenesis "
            "cold response",
            "mitochondrial biogenesis brown adipose thermogenesis "
            "cold response",
            True,
            "verified",
        ),
        (
            "https://example.org/1",
            "this paper studies algebraic topology and category theory",
            "protein folding kinetics in chaperonin complexes",
            True,
            "unsupported",
        ),
    ],
    ids=[
        "unavailable_when_no_url",
        "unavailable_when_flag_false",
        "verified_when_strong_overlap",
        "unsupported_when_no_overlap",
    ],
)
def test_classify_citation(
    url: str, abstract: str, claim: str, available: bool, expected: str
) -> None:
    r = CitationRecord(
        url=url, abstract=abstract, claim=claim, available=available
    )
    assert classify_citation(r) == expected


def test_partial_when_source_states_some_of_the_claim() -> None:
    # Half the claim's concepts appear in the source: relevant, but not the
    # whole assertion.
    r = CitationRecord(
        url="https://example.org/1",
        abstract="mitochondrial biogenesis rises during brown adipose "
        "thermogenesis in a poorly understood pathway",
        claim="mitochondrial biogenesis drives thermogenesis through "
        "uncoupling protein induction",
    )
    assert classify_citation(r) == "partial"


# A real abstract runs several times the length of the claim it is cited for,
# and it discusses background, methods and conclusions the claim never
# mentions. Jaccard divides by the union, which that extra prose dominates,
# so it scored a verbatim quotation at 0.18 -- under the old 0.35 "verified"
# line -- and a relevant paraphrase at 0.078, under the old 0.10 "partial"
# line. One production run classified all 47 of its citations "unsupported"
# with no verified or partial among them. Coverage asks what fraction of the
# claim the source states, which is invariant to the rest of the abstract.
_ABSTRACT_BODY = (
    "Background: glioblastoma remains the most aggressive primary brain "
    "tumour, with median survival under fifteen months despite maximal "
    "resection, radiotherapy and temozolomide. Methods: three "
    "patient-derived stem cell lines were treated across a concentration "
    "range and assayed for viability and colony formation. Results: "
    "viability fell dose-dependently while normal astrocytes were spared. "
    "Conclusions: further preclinical evaluation is warranted."
)

_CLAIM = (
    "empagliflozin suppresses proliferation of patient-derived "
    "glioblastoma stem cells by elevating beta-hydroxybutyrate"
)


@pytest.mark.parametrize(
    "abstract",
    [
        f"{_CLAIM}. {_ABSTRACT_BODY}",
        "empagliflozin suppresses proliferation of glioblastoma stem "
        f"cells as beta-hydroxybutyrate rises. {_ABSTRACT_BODY}",
    ],
    ids=["verbatim_claim", "paraphrased_claim"],
)
def test_abstract_length_does_not_suppress_support(abstract: str) -> None:
    # The regression: both of these were "unsupported" before, purely
    # because the surrounding abstract is long.
    r = CitationRecord(
        url="https://example.org/1", abstract=abstract, claim=_CLAIM
    )
    assert classify_citation(r) == "verified"


def test_stating_the_claim_outscores_sharing_its_subject() -> None:
    # A bag-of-words score cannot tell a claim's subject from its assertion,
    # so an abstract in the same field always carries some of the claim's
    # nouns. What must hold is the ordering: an abstract that states the
    # claim scores strictly above one that merely shares its subject matter.
    # Sharpening that gap further is the LLM claim assessor's job
    # (app.claim_verifier), not this deterministic fallback's.
    subject_only = _token_overlap(_CLAIM, _ABSTRACT_BODY)
    stated = _token_overlap(_CLAIM, f"{_CLAIM}. {_ABSTRACT_BODY}")
    assert stated > subject_only
    assert subject_only < 0.60
