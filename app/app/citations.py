"""Citation classification.

Each citation is mapped to one of four states the UI surfaces:

- `verified`    — the source exists, has a stable identifier, and the inline
                  claim appears in the abstract / extracted excerpt.
- `partial`     — the source exists but only partially supports the claim, or
                  the claim is paraphrased beyond what the abstract states.
- `unsupported` — the source exists and contradicts or fails to mention the
                  claim.
- `unavailable` — no resolvable source (broken URL, retracted, no metadata).

In the absence of a real verification corpus the mock implementation uses
deterministic rules over the supplied evidence record so the pipeline produces
stable labels for tests and screenshots.
"""

from __future__ import annotations

import enum
import functools
from dataclasses import dataclass


class CitationState(str, enum.Enum):
    """States the UI surfaces for a single citation."""

    VERIFIED = "verified"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


ALL_STATES: tuple[CitationState, ...] = (
    CitationState.VERIFIED,
    CitationState.PARTIAL,
    CitationState.UNSUPPORTED,
    CitationState.UNAVAILABLE,
)

# Strength rank per state (higher = stronger support), derived from the
# strongest-to-weakest ordering of ALL_STATES.
STATE_RANK: dict[str, int] = {
    state.value: len(ALL_STATES) - 1 - i for i, state in enumerate(ALL_STATES)
}


def empty_citation_summary() -> dict[str, int]:
    """Return a zeroed state -> count summary covering every citation state."""
    return {state.value: 0 for state in ALL_STATES}


@dataclass
class CitationRecord:
    """Inputs the classifier expects per evidence row."""

    url: str = ""
    abstract: str = ""
    claim: str = ""  # the inline claim cited from this source
    available: bool = True


@functools.lru_cache(maxsize=256)
def _content_tokens(text: str) -> frozenset[str]:
    """Cache the token set for a string.

    Claims repeat across a hypothesis's citations, so this collapses their
    re-tokenization to a single pass.
    """
    # Words of length <= 3 (articles, prepositions, etc.) are dropped as noise
    # that would inflate overlap without indicating real semantic match.
    return frozenset(t for t in text.lower().split() if len(t) > 3)


def _token_overlap(claim: str, abstract: str) -> float:
    """How much of the claim's vocabulary the source actually states.

    Coverage (intersection over the *claim's* tokens), not Jaccard. The two
    texts are deliberately asymmetric -- a one-sentence claim against a
    whole abstract -- and Jaccard divides by the union, which the longer
    side dominates. That caps the score near ``len(claim) / len(abstract)``
    however perfectly the source supports the claim: an abstract quoting the
    claim verbatim scored 0.18, below the 0.35 "verified" line, and a
    relevant abstract paraphrasing it scored 0.078, below the 0.10 "partial"
    line. Both upper states were unreachable, so every citation in a real
    run classified "unsupported" (one production run: 0 verified, 0 partial,
    47 unsupported) and the citation audit reported nothing but failure.

    Coverage asks the question the four states are actually about -- what
    fraction of what the claim asserts appears in the cited source -- and is
    invariant to how much else the abstract discusses.
    """
    if not claim or not abstract:
        return 0.0
    a = _content_tokens(claim)
    b = _content_tokens(abstract)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


def classify_citation(record: CitationRecord) -> CitationState:
    """Classify a single citation deterministically.

    Rules:
    - No URL or `available=False` → unavailable.
    - Claim coverage in the abstract >= 0.60 → verified.
    - Coverage >= 0.30 → partial.
    - Otherwise → unsupported.

    The thresholds are stated against coverage (see `_token_overlap`);
    porting the old Jaccard numbers across would have kept both upper states
    unreachable in practice.
    """
    # Availability is checked first so an unresolved source short-circuits
    # before spending a token-overlap computation on it.
    if not record.available or not record.url:
        return CitationState.UNAVAILABLE
    overlap = _token_overlap(record.claim, record.abstract)
    if overlap >= 0.60:
        return CitationState.VERIFIED
    if overlap >= 0.30:
        return CitationState.PARTIAL
    return CitationState.UNSUPPORTED
