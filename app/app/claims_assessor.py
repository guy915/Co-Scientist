"""Deterministic claim retrieval and the offline entailment assessor.

Split out of :mod:`app.claims` to keep that module within the size budget.
This half holds the offline signal layer -- concept tokenization, lexical
retrieval, the contradiction lexicon, and the deterministic assessor that
stands in for an NLI/LLM model so the pipeline and its tests run offline.
:mod:`app.claims` re-exports every public name here, so callers keep importing
from ``app.claims`` exactly as before.

The thresholds below are clone choices, not published Google parameters (SSR
§12), and they govern the *deterministic fallback only* -- the real assessor
(``app/claim_verifier.py``) decides support and partial support from meaning.
"""

from __future__ import annotations

import dataclasses
import functools
import re
from collections.abc import Callable, Sequence

from app.claims_gate import EntailmentLabel

# --- Evidence passages ------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class EvidencePassage:
    """One retrievable evidence passage with its source provenance.

    ``text`` is the passage the assessor reads (e.g. an abstract). ``start``/
    ``end`` support-span offsets index into this exact ``text``.
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


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

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

# Lexical band below full support: a passage clearing this but not the support
# threshold is a near-miss -> PARTIAL. Deterministic-fallback only; the LLM
# assessor decides partial from meaning, not overlap. Kept at half the support
# threshold so a passage must still be clearly on-topic to earn partial.
_PARTIAL_LEXICAL_THRESHOLD = 0.09

# A partial verdict also requires at least this many shared concept tokens. A
# single shared token is topical coincidence (a passage naming the claim's
# subject but bearing on nothing it asserts), which the LLM prompt likewise
# rules out; a near-miss must overlap on two distinct concepts.
_PARTIAL_MIN_SHARED_TOKENS = 2

# Retrieve at most this many passages per claim before assessing (claim-
# specific retrieval): bounds an LLM assessor's context and stops an unrelated
# passage from grounding a claim by run-wide coincidence.
_DEFAULT_RETRIEVAL_TOP_K = 5


@dataclasses.dataclass(frozen=True)
class AssessorDraft:
    """An assessor's raw verdict before spans are located and guarded.

    Assessors return the atomic claim's label and, for supporting/contradicting
    evidence, ``(evidence_id, quote)`` pairs; ``assess_claim`` then locates each
    quote in its cited passage to produce offset-bearing ``SupportSpan``
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


def _best_sentence(claim: str, text: str) -> str:
    """Return the sentence in ``text`` most lexically overlapping ``claim``."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if not sentences:
        return text.strip()
    return max(sentences, key=lambda s: _lexical_score(claim, s))


def _classify_passage(
    claim: str,
    passage: EvidencePassage,
    support_threshold: float,
    partial_threshold: float,
) -> tuple[str, tuple[str, str]] | None:
    """Classify one passage as contradicting, supporting, partial, or neither.

    Only locates the best sentence for passages that actually qualify;
    sentence splitting is wasted work for the rest.

    Returns:
        A ``(kind, (evidence_id, quote))`` pair where ``kind`` is
        ``"contradicts"``, ``"supports"``, or ``"partial"`` (a near-miss that
        clears ``partial_threshold`` but not ``support_threshold``), or
        ``None`` when the passage clears none of the bars.
    """
    score = _lexical_score(claim, passage.text)
    lowered = passage.text.lower()
    has_marker = any(m in lowered for m in _CONTRADICTION_MARKERS)
    if has_marker and score >= support_threshold / 2:
        quote = _best_sentence(claim, passage.text)
        return "contradicts", (passage.evidence_id, quote)
    if score >= support_threshold:
        quote = _best_sentence(claim, passage.text)
        return "supports", (passage.evidence_id, quote)
    shared = len(_tokens(claim) & _tokens(passage.text))
    if score >= partial_threshold and shared >= _PARTIAL_MIN_SHARED_TOKENS:
        quote = _best_sentence(claim, passage.text)
        return "partial", (passage.evidence_id, quote)
    return None


def _entailment_label(
    supporting: Sequence[tuple[str, str]],
    partial: Sequence[tuple[str, str]],
    contradicting: Sequence[tuple[str, str]],
) -> EntailmentLabel:
    """Pick the overall label for a claim.

    Precedence: a contradiction dominates any support; failing that, full
    support beats a partial (near-miss) match; a partial-only claim is
    PARTIAL; nothing relevant is INSUFFICIENT.
    """
    if contradicting:
        return EntailmentLabel.CONTRADICTS
    if supporting:
        return EntailmentLabel.SUPPORTS
    if partial:
        return EntailmentLabel.PARTIAL
    return EntailmentLabel.INSUFFICIENT


def deterministic_assessor(
    claim: str,
    passages: Sequence[EvidencePassage],
    *,
    support_threshold: float = _SUPPORT_LEXICAL_THRESHOLD,
    partial_threshold: float = _PARTIAL_LEXICAL_THRESHOLD,
) -> AssessorDraft:
    """Offline entailment stand-in: lexical support + a contradiction lexicon.

    Contradiction dominates: a related passage carrying a negation marker
    contradicts the claim regardless of other support. Otherwise a passage
    clearing the lexical support threshold supports it; one clearing only the
    (lower) partial threshold is a near-miss (PARTIAL); nothing sufficient is
    INSUFFICIENT. Partial passages are still cited as supporting spans -- the
    difference from full support is the label, not the provenance -- so the
    badge and report can locate the exact passage behind a partial verdict.
    Cites the single best-overlapping sentence of each relevant passage as the
    quote, so ``assess_claim`` can locate an exact span.
    """
    supporting: list[tuple[str, str]] = []
    partial: list[tuple[str, str]] = []
    contradicting: list[tuple[str, str]] = []
    for passage in passages:
        classified = _classify_passage(
            claim, passage, support_threshold, partial_threshold
        )
        if classified is None:
            continue
        kind, entry = classified
        if kind == "contradicts":
            contradicting.append(entry)
        elif kind == "supports":
            supporting.append(entry)
        else:
            partial.append(entry)

    return AssessorDraft(
        label=_entailment_label(supporting, partial, contradicting),
        supporting=tuple(supporting) + tuple(partial),
        contradicting=tuple(contradicting),
    )
