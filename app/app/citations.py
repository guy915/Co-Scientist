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
from collections.abc import Iterable
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


@dataclass
class CitationRecord:
    """Inputs the classifier expects per evidence row."""

    title: str = ""
    url: str = ""
    abstract: str = ""
    claim: str = ""  # the inline claim cited from this source
    available: bool = True


def _token_overlap(claim: str, abstract: str) -> float:
    """Lower-bound semantic match: jaccard over lower-cased word tokens."""
    if not claim or not abstract:
        return 0.0
    a = {t for t in claim.lower().split() if len(t) > 3}
    b = {t for t in abstract.lower().split() if len(t) > 3}
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def classify_citation(record: CitationRecord) -> CitationState:
    """Classify a single citation deterministically.

    Rules:
    - No URL or `available=False` → unavailable.
    - Token overlap with claim >= 0.35 → verified.
    - Overlap >= 0.10 → partial.
    - Otherwise → unsupported.
    """
    if not record.available or not record.url:
        return CitationState.UNAVAILABLE
    overlap = _token_overlap(record.claim, record.abstract)
    if overlap >= 0.35:
        return CitationState.VERIFIED
    if overlap >= 0.10:
        return CitationState.PARTIAL
    return CitationState.UNSUPPORTED


def classify_many(records: Iterable[CitationRecord]) -> list[CitationState]:
    return [classify_citation(r) for r in records]
