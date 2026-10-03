"""Deterministic claim retrieval and the offline entailment assessor."""

from __future__ import annotations

import dataclasses
import functools
import re
from collections.abc import Callable, Sequence

from app.claims.gate import EntailmentLabel

RETRIEVAL_STOPWORDS = frozenset(
    {
        "a",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "did",
        "do",
        "for",
        "few",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "him",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "no",
        "nor",
        "not",
        "of",
        "off",
        "on",
        "or",
        "our",
        "out",
        "own",
        "per",
        "she",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "too",
        "up",
        "us",
        "via",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "yet",
        "you",
        "your",
    }
)

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


# Public: claim extraction, evidence chunking and the citation drain all
# split prose on this one boundary, so they agree on what a sentence is.
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Phrases that flip a passage's polarity toward contradiction. Deterministic
# stand-in for an NLI contradiction signal; the real assessor is an LLM/NLI
# model (see app/claims/verifier.py).
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
# Stated against coverage (see _lexical_score): a majority of what the claim
# asserts must appear in the passage.
#
# Derived by measuring, not by tuning between two examples. Over a cross
# product of nine real PubMed title+abstract passages (three topics) against
# claims drawn from each paper's own conclusion, the unrelated cross-topic
# population topped out at 0.462 coverage; 0.50 is the lowest round line above
# it, and no cross-topic pair reaches SUPPORTS there. Moving it either way is
# strictly worse: at 0.60 the genuinely-supporting-but-paraphrased population
# falls from 3/9 to 0/9 supports while unrelated leakage is already zero, and
# at 0.40 same-topic-different-assertion pairs start clearing it (2/18 -> 4/18).
_SUPPORT_LEXICAL_THRESHOLD = 0.50

# Lexical band below full support: a passage clearing this but not the support
# threshold is a near-miss -> PARTIAL. Deterministic-fallback only; the LLM
# assessor decides partial from meaning, not overlap. Kept at half the support
# threshold so a passage must still be clearly on-topic to earn partial.
#
# This line is weaker evidence than the support line above, and is stated as
# such: no coverage value cleanly separates a near-miss from an unrelated
# passage. 0.25 sits above the unrelated population's 75th percentile (0.179)
# and excludes 48 of 54 of them, which is the most the metric can do alone --
# the residual is what _PARTIAL_MIN_SHARED_TOKENS and claim-specific retrieval
# (retrieve_passages) are for.
_PARTIAL_LEXICAL_THRESHOLD = 0.25

# A partial verdict also requires at least this many shared concept tokens. A
# single shared token is topical coincidence (a passage naming the claim's
# subject but bearing on nothing it asserts), which the LLM prompt likewise
# rules out; a near-miss must overlap on two distinct concepts.
_PARTIAL_MIN_SHARED_TOKENS = 2

# How much of a claim's own concept tokens a quote cited as contradicting it
# must state before that contradiction is believed (see
# :func:`_quote_negates_claim`). Deliberately the same 0.25 as the partial
# band above -- a quote too unrelated to earn PARTIAL support cannot be
# specific enough to refute the claim either -- so this is one line, not a
# separately tuned one.
_MIN_CONTRADICTION_COVERAGE = _PARTIAL_LEXICAL_THRESHOLD

# Retrieve at most this many passages per claim before assessing (claim-
# specific retrieval): bounds an LLM assessor's context and stops an unrelated
# passage from grounding a claim by run-wide coincidence.
_DEFAULT_RETRIEVAL_TOP_K = 5


@dataclasses.dataclass(frozen=True)
class AssessorDraft:
    """An assessor's raw verdict before spans are located and guarded.

    Assessors return the atomic claim's label and, for supporting/contradicting
    evidence, ``(cited_key, quote)`` pairs; ``assess_claim`` then locates each
    quote in its cited passage to produce offset-bearing ``SupportSpan``
    objects and downgrades a verdict whose quotes cannot be located (an
    anti-hallucination provenance guard). Internal assessors cite evidence
    IDs directly; model parsers mark prompt-position citations explicitly.
    """

    label: EntailmentLabel
    supporting: tuple[tuple[str, str], ...] = ()
    contradicting: tuple[tuple[str, str], ...] = ()
    verification_method: str = "legacy_unknown"
    cites_evidence_ids: bool = True


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
    """How much of the claim's vocabulary the passage states.

    Coverage (intersection over the *claim's* tokens), not Jaccard, for the
    same reason ``citations._token_overlap`` is: the two texts are
    deliberately asymmetric. A ``EvidencePassage`` is an evidence row's title
    plus abstract (``claims.grounding.evidence_passages``) -- 1000-2000
    characters, 70-170 concept tokens -- and a claim is one sentence, 8-28 of
    them. Jaccard divides by the union, which the longer side dominates, so
    the score cannot exceed ``len(claim) / len(claim | passage)`` however
    perfectly the passage supports the claim.

    That ceiling sat *below the thresholds it was compared against*. Measured
    over nine real PubMed title+abstract passages, the ceiling ranged 0.054 to
    0.224 against a 0.18 support line: an abstract carrying the claim verbatim
    reached SUPPORTS in 3 of 9 cases and was scored INSUFFICIENT in 2, and of
    the genuinely-supporting passages that paraphrase rather than quote,
    *none* could reach SUPPORTS -- 0 of 9. One worked example: the claim
    "Inhibition of FLT3 reduces proliferation of leukemic blasts in acute
    myeloid leukemia" against an abstract literally containing that sentence
    scored 0.060, missing not just the 0.18 support line but the 0.09 partial
    line too, so both upper states were unreachable. This is the same defect
    ``citations.classify_citation`` carried (verbatim quote scoring 0.18
    against a 0.35 line, every citation in every real run "unsupported"); it
    reads as poor evidence quality rather than as a metric bug because the
    numbers are individually plausible.

    Coverage asks what the label is actually about -- what fraction of what
    the claim asserts the passage states -- and is invariant to how much else
    the passage discusses. It is a retrieval/fallback signal, not a verdict:
    a bag of words cannot tell a claim's subject from its assertion, so an
    abstract on the claim's topic that asserts something else scores as high
    as one that supports it. Discriminating those is the LLM entailment
    assessor's job (``claims.verifier``); this scorer's job is only to stop
    capping the states it is compared against.
    """
    a, b = _tokens(claim), _tokens(passage)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


@functools.lru_cache(maxsize=256)
def _retrieval_tokens(text: str) -> frozenset[str]:
    """Retain short content terms for recall, never for verdict scoring."""
    short = {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) <= 3 and not token.isdigit()
    }
    return (_tokens(text) | short) - RETRIEVAL_STOPWORDS


def retrieve_passages(
    claim: str,
    passages: Sequence[EvidencePassage],
    *,
    top_k: int = _DEFAULT_RETRIEVAL_TOP_K,
) -> list[EvidencePassage]:
    """Rank passages by relevance to ``claim`` and return the top ``top_k``.

    Claim-specific retrieval: the assessor sees only the passages most likely
    to bear on this claim, not the entire run-wide pool. Ranking is by lexical
    overlap including short content terms; ties keep input order stable.
    Zero-overlap passages are dropped. A retrieved passage is only a candidate;
    its entailment still requires assessment.

    Args:
        claim: The atomic claim being grounded.
        passages: The run's candidate evidence passages.
        top_k: Maximum passages to return.

    Returns:
        The most relevant passages, most-relevant first.
    """
    query = _retrieval_tokens(claim)
    scored = [
        (i, p, len(query & _retrieval_tokens(p.text)))
        for i, p in enumerate(passages)
    ]
    relevant = [(i, p, s) for i, p, s in scored if s > 0.0]
    relevant.sort(key=lambda t: (-t[2], t[0]))
    return [p for _, p, _ in relevant[: max(0, top_k)]]


def _quote_negates_claim(claim: str, quote: str) -> bool:
    """Whether a quote cited as contradicting ``claim`` is actually founded.

    Two cheap, offline checks for lexical contradictions: the quote has
    to cover the claim's
    subject (at least ``_MIN_CONTRADICTION_COVERAGE`` of the claim's own
    concept tokens, so "kinase antagonist" and "kinase blocker" count as
    the same concept), and it has to carry an actual negation/contrast cue
    from :data:`_CONTRADICTION_MARKERS`.

    Markerless LLM contradictions need a separate semantic check in
    ``claims.verifier_opposition``; this predicate stays conservative.

    Lives here rather than in ``claims.verifier`` (which called it on the
    LLM judge's drafts alone) because the deterministic assessor below
    needs the same predicate -- see :func:`_contradicting_sentence`.

    Measured on two production runs. Ultra run b82f9162 (2026-09-06): 105
    of 183 claim-evidence edges came back CONTRADICTS from the LLM judge,
    including a quote about a different drug/target entirely (subject
    coverage far below the bar) and a quote stating the claim's own
    mechanism (on-topic, no negation at all). Standard run e47a3ba1
    (2026-09-08): 11 of 101 edges, none of them from the LLM judge at all
    -- zero of those 11 quotes contained any marker, and 10 of 11 also
    fell below the coverage bar.
    """
    claim_tokens = _tokens(claim)
    if not claim_tokens:
        return False
    coverage = len(claim_tokens & _tokens(quote)) / len(claim_tokens)
    if coverage < _MIN_CONTRADICTION_COVERAGE:
        return False
    lowered = quote.lower()
    return any(marker in lowered for marker in _CONTRADICTION_MARKERS)


def _contradicting_sentence(claim: str, text: str) -> str | None:
    """The passage's best sentence that actually negates ``claim``.

    Deliberately *not* ``_best_sentence``: the sentence stating the most
    of a claim is the one least likely to be its negation. The marker used
    to be tested against the whole passage while the cited quote came from
    ``_best_sentence``, so a passage carrying an unrelated negation
    ("body weight did not differ between groups") contradicted the claim
    and cited a sentence asserting the claim's own direction -- production
    run e47a3ba1 shipped 11 such edges, one of them a quote reporting the
    very reduction the claim predicted (see the module test
    ``tests/test_claims_contradiction_quote.py``).

    Returns None when no sentence in the passage is a founded negation, in
    which case the passage is scored for support like any other.
    """
    negating = [
        sentence
        for sentence in _split_sentences(text)
        if _quote_negates_claim(claim, sentence)
    ]
    if not negating:
        return None
    return max(negating, key=lambda s: _lexical_score(claim, s))


def _split_sentences(text: str) -> list[str]:
    """Split ``text`` into non-empty, stripped sentences."""
    return [s.strip() for s in SENTENCE_SPLIT.split(text) if s.strip()]


def _best_sentence(claim: str, text: str) -> str:
    """Return the sentence in ``text`` stating the most of ``claim``.

    The one place ``_lexical_score`` is an argmax rather than a threshold
    test, so the cap it was changed to remove never applied here. Coverage
    divides by the claim, which is constant across candidates, making this
    exactly "the sentence containing the most claim tokens"; ties keep the
    earliest sentence, since ``max`` returns the first maximal element.
    """
    sentences = _split_sentences(text)
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

    A contradiction is cited by the sentence that actually negates the
    claim (:func:`_contradicting_sentence`), not by the sentence stating
    the most of it; a passage with no such sentence is scored for support
    like any other. The passage-level ``support_threshold / 2`` bar is
    unchanged and still gates the branch -- the sentence-level check is an
    additional condition, not a moved threshold.

    Only locates the best sentence for passages that actually qualify;
    sentence splitting is wasted work for the rest.

    Returns:
        A ``(kind, (evidence_id, quote))`` pair where ``kind`` is
        ``"contradicts"``, ``"supports"``, or ``"partial"`` (a near-miss that
        clears ``partial_threshold`` but not ``support_threshold``), or
        ``None`` when the passage clears none of the bars.
    """
    score = _lexical_score(claim, passage.text)
    if score >= support_threshold / 2:
        negation = _contradicting_sentence(claim, passage.text)
        if negation is not None:
            return "contradicts", (passage.evidence_id, negation)
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
        verification_method="deterministic_lexical"
        if passages
        else "no_evidence",
        cites_evidence_ids=True,
    )
