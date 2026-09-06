"""Locating a cited quote in its passage, and the anti-hallucination guard.

Split out of :mod:`app.claims` to keep that module within the size
budget. Both the single-claim path (``claims.assess_claim``) and the
batched path (``claims_batch.assess_claims_batch``) need to turn an
assessor's raw ``(evidence_id, quote)`` citation into an offset-bearing
``SupportSpan`` and downgrade a verdict whose citation cannot be located
-- this module is the one place that logic lives, imported by both
without either importing the other.

:mod:`app.claims` re-exports :func:`locate_span`, since it is public API
(tests and callers import it from there); the underscore-prefixed names
are private, shared implementation detail.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.claims_assessor import EvidencePassage
from app.claims_gate import EntailmentLabel, SupportSpan

_WHITESPACE_RE = re.compile(r"\s+")
# Curly quotes/dashes an LLM may substitute for their straight ASCII forms.
_QUOTE_NORMALIZE = str.maketrans(
    {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-"}  # noqa: RUF001
)


def _straighten(text: str) -> str:
    """Normalize curly quotes/dashes to their straight ASCII forms."""
    return text.translate(_QUOTE_NORMALIZE)


def locate_span(passage: EvidencePassage, quote: str) -> SupportSpan | None:
    """Locate ``quote`` inside ``passage.text`` and return its exact span.

    Matching is whitespace- and case-insensitive and tolerant of curly-quote
    substitution, because an LLM assessor commonly returns a quote whose
    whitespace/casing/punctuation differs slightly from the source. The
    returned span's ``quote`` is the verbatim source substring at the located
    offsets (not the assessor's paraphrase), so the offsets are exact.

    Returns:
        The located :class:`SupportSpan`, or None when the quote cannot be
        found in the passage (the caller treats an unlocatable quote as
        unproven).
    """
    normalized_quote = _WHITESPACE_RE.sub(" ", _straighten(quote)).strip()
    if not normalized_quote:
        return None
    tokens = normalized_quote.split(" ")
    # Whitespace-flexible, case-insensitive pattern over the original text so
    # the match offsets index into passage.text directly.
    pattern = r"\s+".join(re.escape(t) for t in tokens)
    match = re.search(pattern, _straighten(passage.text), flags=re.IGNORECASE)
    if match is None:
        return None
    start, end = match.start(), match.end()
    return SupportSpan(
        evidence_id=passage.evidence_id,
        quote=passage.text[start:end],
        start=start,
        end=end,
        source=passage.source,
        url=passage.url,
    )


def _downgrade_unproven_label(
    label: EntailmentLabel,
    supporting: list[SupportSpan],
    contradicting: list[SupportSpan],
) -> EntailmentLabel:
    """Downgrade a verdict lacking a locatable span to INSUFFICIENT.

    Anti-hallucination provenance guard: a SUPPORTS/PARTIAL/CONTRADICTS verdict
    must be backed by at least one locatable span, else it is unproven. A
    PARTIAL claim cites its near-miss passage as a supporting span, so it is
    guarded against the same ``supporting`` list as SUPPORTS.
    """
    supporting_labels = (EntailmentLabel.SUPPORTS, EntailmentLabel.PARTIAL)
    if (label in supporting_labels and not supporting) or (
        label is EntailmentLabel.CONTRADICTS and not contradicting
    ):
        return EntailmentLabel.INSUFFICIENT
    return label


def _locate_all(
    cited: Sequence[tuple[str, str]],
    by_id: dict[str, EvidencePassage],
) -> list[SupportSpan]:
    """Locate every ``(evidence_id, quote)`` pair, dropping unlocatable ones."""
    spans: list[SupportSpan] = []
    for evidence_id, quote in cited:
        passage = by_id.get(evidence_id)
        if passage is None:
            continue
        span = locate_span(passage, quote)
        if span is not None:
            spans.append(span)
    return spans
