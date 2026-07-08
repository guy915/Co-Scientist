"""Citation classification.

Each citation is mapped to one of four states the UI surfaces:

- `verified`    — the source exists, has a stable identifier, and the inline claim  # pylint: disable=line-too-long
                  appears in the abstract / extracted excerpt.
- `partial`     — the source exists but only partially supports the claim, or the  # pylint: disable=line-too-long
                  claim is paraphrased beyond what the abstract states.
- `unsupported` — the source exists and contradicts or fails to mention the claim.  # pylint: disable=line-too-long
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
    """Cache the token set for a string; claims repeat across a hypothesis's
    citations, so this collapses their re-tokenization to a single pass."""
    # Words of length <= 3 (articles, prepositions, etc.) are dropped as noise
    # that would inflate overlap without indicating real semantic match.
    return frozenset(t for t in text.lower().split() if len(t) > 3)


def _token_overlap(claim: str, abstract: str) -> float:
    """Lower-bound semantic match: jaccard over lower-cased word tokens."""
    if not claim or not abstract:
        return 0.0
    a = _content_tokens(claim)
    b = _content_tokens(abstract)
    if not a or not b:
        return 0.0
    # Jaccard similarity: intersection over union of the two token sets.
    return len(a & b) / len(a | b)


def classify_citation(record: CitationRecord) -> CitationState:
    """Classify a single citation deterministically.

    Rules:
    - No URL or `available=False` → unavailable.
    - Token overlap with claim >= 0.35 → verified.
    - Overlap >= 0.10 → partial.
    - Otherwise → unsupported.
    """
    # Availability is checked first so an unresolved source short-circuits
    # before spending a token-overlap computation on it.
    if not record.available or not record.url:
        return CitationState.UNAVAILABLE
    overlap = _token_overlap(record.claim, record.abstract)
    if overlap >= 0.35:
        return CitationState.VERIFIED
    if overlap >= 0.10:
        return CitationState.PARTIAL
    return CitationState.UNSUPPORTED
