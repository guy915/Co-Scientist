"""Citation classification.

Each citation is mapped to one of four states the UI surfaces:

- `verified`    — the source exists, has a stable identifier, and the inline claim
                  appears in the abstract / extracted excerpt.
- `partial`     — the source exists but only partially supports the claim, or the
                  claim is paraphrased beyond what the abstract states.
- `unsupported` — the source exists and contradicts or fails to mention the claim.
- `unavailable` — no resolvable source (broken URL, retracted, no metadata).

In the absence of a real verification corpus the mock implementation uses
deterministic rules over the supplied evidence record so the pipeline produces
stable labels for tests and screenshots.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

CitationState = Literal["verified", "partial", "unsupported", "unavailable"]
ALL_STATES: tuple[CitationState, ...] = ("verified", "partial", "unsupported", "unavailable")


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
        return "unavailable"
    overlap = _token_overlap(record.claim, record.abstract)
    if overlap >= 0.35:
        return "verified"
    if overlap >= 0.10:
        return "partial"
    return "unsupported"


def classify_many(records: Iterable[CitationRecord]) -> list[CitationState]:
    return [classify_citation(r) for r in records]
