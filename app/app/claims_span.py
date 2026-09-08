"""Locating a cited quote in its passage, and the anti-hallucination guard.

Split out of :mod:`app.claims` to keep that module within the size
budget. Both the single-claim path (``claims.assess_claim``) and the
batched path (``claims_batch.assess_claims_batch``) need to turn an
assessor's raw ``(cited_key, quote)`` citation into an offset-bearing
``SupportSpan`` and downgrade a verdict whose citation cannot be located
-- this module is the one place that logic lives, imported by both
without either importing the other.

``cited_key`` is normally the passage's bracketed prompt number now, not
its evidence id: production run bc77950f lost most of a run's entailment
verdicts (8 of 13 hypotheses drew zero supported claims, on-topic
evidence sitting unused in their retrieval pool) because the prompt
required an exact 36-character id echoed back and a fallback model
formatted it differently. ``claim_verifier`` and ``claim_verifier_batch``
now ask for the short number instead (see their ``_CITATION_ITEM``); a
literal id -- with or without its chunk suffix -- is still accepted here
as a fallback for a model that cites one anyway, not the contract itself.

:mod:`app.claims` re-exports :func:`locate_span`, since it is public API
(tests and callers import it from there); the underscore-prefixed names
are private, shared implementation detail.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from app.claims_assessor import EvidencePassage
from app.claims_gate import EntailmentLabel, SupportSpan
from app.evidence_chunking import parent_evidence_id

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
# A citation naming the passage's *number* rather than its evidence id --
# "3", "[3]", "(3)", "passage 3". The entailment prompt renders every
# passage as "[<n>] <text>" (claim_verifier._render_passages) and asks for
# exactly this number back, so it is the primary, expected citation form,
# not a fallback.
_POSITIONAL_KEY = re.compile(
    r"^[\[(]?\s*(?:passage|evidence)?\s*(\d{1,3})\s*[\])]?$", re.IGNORECASE
)
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


def _normalize_key(cited_key: str) -> str:
    """Canonical form of the key an assessor cited a passage by."""
    key = _WHITESPACE_RE.sub(" ", cited_key).strip()
    positional = _POSITIONAL_KEY.match(key)
    return positional.group(1) if positional else key.casefold()


def _passage_lookup(
    passages: Sequence[EvidencePassage],
) -> dict[str, EvidencePassage]:
    """Map every key a passage may plausibly be cited by to that passage.

    Three keys per passage: its own evidence id, that id stripped of its
    ``#<chunk>`` suffix (a model citing the article rather than the chunk
    it was shown), and its 1-based position in the prompt. Real ids are
    registered first so a positional key can never shadow one, and the
    first passage claiming a key keeps it.
    """
    lookup: dict[str, EvidencePassage] = {}
    for passage in passages:
        for key in (
            passage.evidence_id,
            parent_evidence_id(passage.evidence_id),
        ):
            lookup.setdefault(_normalize_key(key), passage)
    for position, passage in enumerate(passages, start=1):
        lookup.setdefault(str(position), passage)
    return lookup


def _resolve_span(
    cited_key: str,
    quote: str,
    passages: Sequence[EvidencePassage],
    lookup: dict[str, EvidencePassage],
) -> SupportSpan | None:
    """Locate one cited quote, by its named passage or by the quote itself.

    The named passage is tried first, so a correctly cited quote records
    the provenance the assessor meant. Failing that the quote is searched
    for across the passages the assessor was actually shown, which
    re-attributes a verbatim quote filed under the wrong id instead of
    discarding the verdict it justifies -- the id is the assessor's
    bookkeeping, the quote is the evidence.
    """
    named = lookup.get(_normalize_key(cited_key))
    if named is not None:
        span = locate_span(named, quote)
        if span is not None:
            return span
    for passage in passages:
        span = locate_span(passage, quote)
        if span is not None:
            return span
    return None


def _locate_all(
    cited: Sequence[tuple[str, str]],
    passages: Sequence[EvidencePassage],
) -> list[SupportSpan]:
    """Locate every ``(evidence_id, quote)`` pair, dropping unlocatable ones.

    A pair survives only if its quote is verbatim (whitespace/case/curly-
    quote tolerant) in one of the passages the assessor was shown -- the
    anti-hallucination guarantee ``_downgrade_unproven_label`` rests on.
    What is *not* required is that the assessor named that passage
    correctly; see :func:`_resolve_span`.

    Drops are logged because they are otherwise invisible: they surface
    only as an INSUFFICIENT verdict, indistinguishable from an assessor
    that found nothing (production run bc77950f -- see the module
    docstring).
    """
    lookup = _passage_lookup(passages)
    spans: list[SupportSpan] = []
    dropped = 0
    for evidence_id, quote in cited:
        span = _resolve_span(evidence_id, quote, passages, lookup)
        if span is None:
            dropped += 1
        else:
            spans.append(span)
    if dropped:
        logger.warning(
            "%d cited span(s) could not be located in any of the %d "
            "passage(s) shown to the assessor; verdict unproven",
            dropped,
            len(passages),
        )
    return spans
