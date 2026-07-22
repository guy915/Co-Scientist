"""Claim-level grounding, entailment, and publication gating (Milestone 5).

The four-state citation label (``app/citations.py``) is a document-level audit
signal; it is *not* claim-level verification and must not be the meaning of
"verified". This module adds the claim-level layer the paper
requires (SSR §6, §7):

1. **Atomic claim extraction** — split a hypothesis / mechanism / experiment /
   report into atomic claims.
2. **Claim-specific retrieval** — for each claim, rank the run's evidence
   passages by relevance and assess only the most relevant few (not the whole
   run-wide pool), so a passage that happens to share a word with an unrelated
   claim cannot ground it.
3. **Per-claim entailment** — for each claim, assess the retrieved evidence as
   SUPPORTS / CONTRADICTS / INSUFFICIENT via a swappable *assessor*, recording
   the exact supporting/contradicting **span** (source evidence id, quoted
   text, and character offsets) plus the assessor provenance. The stored span
   is what lets a displayed verified claim open its exact supporting passage.
4. **Resolvability, separately** — whether a citation's source resolves
   (URL/metadata/retraction) is judged independently of whether it supports the
   claim, via a swappable *resolver* (offline metadata by default; a live
   URL/DOI/retraction lookup is injectable).
5. **Publication gate** — an unsupported or contradicted *fundamental* claim
   cannot let a hypothesis rank/publish; clearly labeled speculation is allowed
   only under an explicit policy flag.

The default assessor is deterministic (a contradiction lexicon plus a lexical
support fallback) so the pipeline and its tests run offline. A real NLI/LLM
entailment assessor is a documented, swappable, provenance-tagged drop-in
(``app/claim_verifier.py``); it is exercised end-to-end by the golden run
rather than in the offline suite. Google does not publish its entailment model
or thresholds (SSR §12), so those are documented clone choices.
"""

from __future__ import annotations

import dataclasses
import functools
import re
from collections.abc import Callable, Sequence

# The entailment verdict enum, provenance support span, claim-assessment
# record, resolvability check, and publication gate were split into
# app/claims_gate.py to keep this module within the size budget. They are
# imported back and re-exported (redundant aliases) so every public name stays
# importable from app.claims exactly as before.
from app.claims_gate import (
    CitationMetadata as CitationMetadata,
)
from app.claims_gate import (
    ClaimAssessment as ClaimAssessment,
)
from app.claims_gate import (
    EntailmentLabel as EntailmentLabel,
)
from app.claims_gate import (
    GateDecision as GateDecision,
)
from app.claims_gate import (
    GateResult as GateResult,
)
from app.claims_gate import (
    Resolvability as Resolvability,
)
from app.claims_gate import (
    Resolver as Resolver,
)
from app.claims_gate import (
    SupportSpan as SupportSpan,
)
from app.claims_gate import (
    assess_resolvability as assess_resolvability,
)
from app.claims_gate import (
    offline_resolver as offline_resolver,
)
from app.claims_gate import (
    publication_gate as publication_gate,
)

# --- Atomic claim extraction ------------------------------------------------

# A claim must have some substance; drop fragments below this word count.
_MIN_CLAIM_WORDS = 4
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def extract_atomic_claims(text: str) -> list[str]:
    """Split a passage into atomic claims (sentence-level), de-noised.

    Sentences shorter than ``_MIN_CLAIM_WORDS`` words (headings, fragments) are
    dropped. Order is preserved and duplicates removed, so the claim list is a
    stable, auditable decomposition of the source text.

    Args:
        text: The hypothesis / mechanism / experiment / report text.

    Returns:
        The atomic claims, in order of first appearance.
    """
    claims: list[str] = []
    seen: set[str] = set()
    for raw in _SENTENCE_SPLIT.split(text or ""):
        claim = raw.strip()
        if len(claim.split()) < _MIN_CLAIM_WORDS:
            continue
        key = claim.lower()
        if key in seen:
            continue
        seen.add(key)
        claims.append(claim)
    return claims


# --- Evidence passages and support spans (provenance) -----------------------


@dataclasses.dataclass(frozen=True)
class EvidencePassage:
    """One retrievable evidence passage with its source provenance.

    ``text`` is the passage the assessor reads (e.g. an abstract). ``start``/
    ``end`` support-span offsets below index into this exact ``text``.
    """

    evidence_id: str
    text: str
    source: str = ""
    url: str = ""


def as_passages(texts: Sequence[str]) -> list[EvidencePassage]:
    """Wrap bare passage strings as synthetic-id ``EvidencePassage`` objects.

    A convenience for callers/tests that only have passage text and no source
    provenance yet; the synthetic id is stable per passage position.
    """
    return [
        EvidencePassage(evidence_id=f"passage-{i}", text=t)
        for i, t in enumerate(texts)
    ]


# --- Per-claim entailment ---------------------------------------------------


# Phrases that flip a passage's polarity toward contradiction. Deterministic
# stand-in for an NLI contradiction signal; the real assessor is an LLM/NLI
# model (see app/claim_verifier.py).
_CONTRADICTION_MARKERS = (
    "no evidence",
    "not associated",
    "no association",
    "does not",
    "did not",
    "failed to",
    "contrary to",
    "contradicts",
    "refutes",
    "disproven",
    "no significant",
    "not significant",
    "ineffective",
    "statistically equivalent",
    "remained equivalent",
    "waned to",
    "returned to baseline",
    "pre-vaccination baseline",
)

# Canonical scientific concepts used by the offline retrieval fallback. This is
# a conservative query-expansion layer, not an entailment model: it helps the
# deterministic assessor find semantically related passages while the final
# label still requires polarity checks and an exact source span.
_CONCEPT_ALIASES = {
    "antagonism": "block",
    "antagonist": "block",
    "blocking": "block",
    "blockade": "block",
    "inhibiting": "inhibit",
    "inhibition": "inhibit",
    "pharmacological": "drug",
    "compound": "drug",
    "agent": "drug",
    "immunization": "vaccine",
    "immunosurveillance": "surveillance",
    "antitumor": "tumor",
    "antibody": "antibody",
    "titers": "response",
    "responses": "response",
    "durable": "persist",
    "survival": "survival",
    "glioblastoma": "glioma",
    "leukemic": "aml",
    "myeloid": "aml",
    "malignancy": "tumor",
    "malignancies": "tumor",
    "proliferation": "growth",
    "curtailed": "reduce",
    "reduces": "reduce",
    "reduced": "reduce",
    "restores": "restore",
    "restored": "restore",
    "established": "restore",
    "eradicated": "effective",
    "effective": "effective",
    "pathogen": "microorganism",
    "infected": "infection",
}

# Clone-defined lexical support threshold used ONLY by the deterministic
# fallback assessor (never the meaning of "verified" for the LLM assessor).
_SUPPORT_LEXICAL_THRESHOLD = 0.18

_ASSESSOR_DETERMINISTIC = "deterministic-v1"

# Retrieve at most this many passages per claim before assessing (claim-
# specific retrieval): bounds an LLM assessor's context and stops an unrelated
# passage from grounding a claim by run-wide coincidence.
_DEFAULT_RETRIEVAL_TOP_K = 5


@dataclasses.dataclass(frozen=True)
class AssessorDraft:
    """An assessor's raw verdict before spans are located and guarded.

    Assessors return the atomic claim's label and, for supporting/contradicting
    evidence, ``(evidence_id, quote)`` pairs; ``assess_claim`` then locates each
    quote in its cited passage to produce offset-bearing :class:`SupportSpan`
    objects and downgrades a verdict whose quotes cannot be located (an
    anti-hallucination provenance guard).
    """

    label: EntailmentLabel
    supporting: tuple[tuple[str, str], ...] = ()
    contradicting: tuple[tuple[str, str], ...] = ()


# An assessor maps (claim, candidate passages) to a raw draft verdict.
Assessor = Callable[[str, Sequence[EvidencePassage]], AssessorDraft]


# Short tokens (length <= 3) are dropped as noise, except these acronyms that
# carry real domain meaning.
_SHORT_TOKEN_EXCEPTIONS = frozenset({"aml"})


@functools.lru_cache(maxsize=256)
def _tokens(text: str) -> frozenset[str]:
    """Normalized concept tokens for deterministic retrieval and fallback.

    Cached because the same claim is re-tokenized across every candidate
    passage during retrieval and assessment.
    """
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        if len(token) <= 3 and token not in _SHORT_TOKEN_EXCEPTIONS:
            continue
        tokens.add(_CONCEPT_ALIASES.get(token, token))
    return frozenset(tokens)


def _lexical_score(claim: str, passage: str) -> float:
    """Jaccard token overlap — a retrieval/fallback signal, not a verdict."""
    a, b = _tokens(claim), _tokens(passage)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def retrieve_passages(
    claim: str,
    passages: Sequence[EvidencePassage],
    *,
    top_k: int = _DEFAULT_RETRIEVAL_TOP_K,
) -> list[EvidencePassage]:
    """Rank passages by relevance to ``claim`` and return the top ``top_k``.

    Claim-specific retrieval: the assessor sees only the passages most likely
    to bear on this claim, not the entire run-wide pool. Ranking is by lexical
    overlap (a deterministic, offline signal); ties keep input order stable.
    Passages with zero overlap are dropped so an unrelated passage cannot be
    assessed against the claim at all.

    Args:
        claim: The atomic claim being grounded.
        passages: The run's candidate evidence passages.
        top_k: Maximum passages to return.

    Returns:
        The most relevant passages, most-relevant first.
    """
    scored = [
        (i, p, _lexical_score(claim, p.text)) for i, p in enumerate(passages)
    ]
    relevant = [(i, p, s) for i, p, s in scored if s > 0.0]
    relevant.sort(key=lambda t: (-t[2], t[0]))
    return [p for _, p, _ in relevant[: max(0, top_k)]]


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


def _best_sentence(claim: str, text: str) -> str:
    """Return the sentence in ``text`` most lexically overlapping ``claim``."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if not sentences:
        return text.strip()
    return max(sentences, key=lambda s: _lexical_score(claim, s))


def deterministic_assessor(
    claim: str,
    passages: Sequence[EvidencePassage],
    *,
    support_threshold: float = _SUPPORT_LEXICAL_THRESHOLD,
) -> AssessorDraft:
    """Offline entailment stand-in: lexical support + a contradiction lexicon.

    Contradiction dominates: a related passage carrying a negation marker
    contradicts the claim regardless of other support. Otherwise a passage
    clearing the lexical support threshold supports it; nothing sufficient is
    INSUFFICIENT. Cites the single best-overlapping sentence of each relevant
    passage as the quote, so ``assess_claim`` can locate an exact span.
    """
    supporting: list[tuple[str, str]] = []
    contradicting: list[tuple[str, str]] = []
    for passage in passages:
        score = _lexical_score(claim, passage.text)
        lowered = passage.text.lower()
        has_marker = any(m in lowered for m in _CONTRADICTION_MARKERS)
        # Only locate the best sentence for passages that actually qualify;
        # sentence splitting is wasted work for the rest.
        if has_marker and score >= support_threshold / 2:
            quote = _best_sentence(claim, passage.text)
            contradicting.append((passage.evidence_id, quote))
        elif score >= support_threshold:
            quote = _best_sentence(claim, passage.text)
            supporting.append((passage.evidence_id, quote))

    if contradicting:
        label = EntailmentLabel.CONTRADICTS
    elif supporting:
        label = EntailmentLabel.SUPPORTS
    else:
        label = EntailmentLabel.INSUFFICIENT
    return AssessorDraft(
        label=label,
        supporting=tuple(supporting),
        contradicting=tuple(contradicting),
    )


def assess_claim(
    claim: str,
    passages: Sequence[EvidencePassage],
    *,
    assessor: Assessor = deterministic_assessor,
    assessor_id: str = _ASSESSOR_DETERMINISTIC,
    top_k: int = _DEFAULT_RETRIEVAL_TOP_K,
) -> ClaimAssessment:
    """Assess a claim against evidence, returning a provenance-stamped verdict.

    Retrieves the most relevant passages for the claim, runs the (swappable)
    ``assessor``, then locates each cited quote in its passage to produce
    offset-bearing spans. A verdict whose cited quotes cannot be located is
    downgraded to INSUFFICIENT (an anti-hallucination provenance guard).
    Every verdict records the exact spans that drove it and the assessor id.

    Args:
        claim: The atomic claim being assessed.
        passages: The run's candidate evidence passages.
        assessor: The entailment assessor (deterministic by default; an
            LLM/NLI assessor is a swappable drop-in).
        assessor_id: Provenance id recorded on the assessment.
        top_k: Claim-specific retrieval budget.

    Returns:
        The claim's :class:`ClaimAssessment`.
    """
    candidates = retrieve_passages(claim, passages, top_k=top_k)
    by_id = {p.evidence_id: p for p in candidates}
    draft = assessor(claim, candidates)
    supporting = _locate_all(draft.supporting, by_id)
    contradicting = _locate_all(draft.contradicting, by_id)
    label = _downgrade_unproven_label(draft.label, supporting, contradicting)
    return ClaimAssessment(
        claim=claim,
        label=label,
        supporting_passages=tuple(supporting),
        contradicting_passages=tuple(contradicting),
        assessor=assessor_id,
    )


def _downgrade_unproven_label(
    label: EntailmentLabel,
    supporting: list[SupportSpan],
    contradicting: list[SupportSpan],
) -> EntailmentLabel:
    """Downgrade a verdict lacking a locatable span to INSUFFICIENT.

    Anti-hallucination provenance guard: a SUPPORTS/CONTRADICTS verdict must
    be backed by at least one locatable span, else it is unproven.
    """
    if (label is EntailmentLabel.SUPPORTS and not supporting) or (
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
