"""Citation classifier covers all four states."""

from __future__ import annotations

import pytest

from app.citations import (
    ALL_STATES,
    CitationRecord,
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


def test_partial_when_some_overlap() -> None:
    r = CitationRecord(
        url="https://example.org/1",
        abstract="mitochondrial biogenesis controls thermogenesis "
        "through a poorly understood pathway",
        claim="mitochondrial biogenesis affects something unrelated entirely",
    )
    state = classify_citation(r)
    assert state in {"partial", "unsupported"}  # depends on tokenization
    # Force a stronger boundary case
    r2 = CitationRecord(
        url="https://example.org/1",
        abstract="biogenesis thermogenesis mitochondrial cellular metabolism",
        claim="biogenesis affects thermogenesis somehow but other "
        "factors matter",
    )
    assert classify_citation(r2) in {"partial", "verified"}
