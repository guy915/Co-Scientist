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

import re
from collections.abc import Sequence

from app.claims_assessor import (
    _DEFAULT_RETRIEVAL_TOP_K,
    _SENTENCE_SPLIT,
)

# --- Retrieval and the deterministic assessor -------------------------------
# The evidence passage, assessor draft, concept tokenizer, claim-specific
# retrieval, and the offline deterministic assessor were split into
# app/claims_assessor.py to keep this module within the size budget. They are
# imported back and re-exported (redundant aliases) so every public name stays
# importable from app.claims exactly as before.
from app.claims_assessor import (
    Assessor as Assessor,
)
from app.claims_assessor import (
    AssessorDraft as AssessorDraft,
)
from app.claims_assessor import (
    EvidencePassage as EvidencePassage,
)
from app.claims_assessor import (
    as_passages as as_passages,
)
from app.claims_assessor import (
    deterministic_assessor as deterministic_assessor,
)
from app.claims_assessor import (
    retrieve_passages as retrieve_passages,
)

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

# A sentence asserting that prior work is *absent* -- "no source tests X",
# "unexplored in the retrieved literature", "has not been tested" -- is a
# novelty statement about the corpus, not an empirical claim about the world.
# It must never reach the entailment layer: it is a negative existential over
# the very passages the assessor entails against, so no passage can confirm it
# and any topical passage reads as contradicting it. A generation prompt asks
# for exactly these sentences (the literature-grounding rationale is meant to
# name the gap the idea fills), which is why they arrive on nearly every
# hypothesis rather than occasionally.
#
# The cost of leaving them in was the run collapsing: once literature
# retrieval started returning full-text papers, six of eight ideas in an
# express run were quarantined ``evidence_blocked`` on one such sentence
# apiece, the pool fell below two rankable ideas, and the scheduler answered
# by generating more ideas that died the same way. Novelty is judged on the
# reviewers' own novelty axis (and the ``non_novel`` disposition), never here.
_EVIDENCE_GAP_CLAIM = re.compile(
    r"""
      \bun(?:explored|examined|tested|studied|addressed|proven
            |characteri[sz]ed)\b
    | \b(?:has|have|had)\ not\ been\b
    | \bnot\ (?:yet\ )?(?:been\ )?(?:\w+ly\ )?
        (?:tested|explored|examined|studied|addressed|established|proven
          |demonstrated|reported|characteri[sz]ed|investigated)\b
    | \bno\ (?:source|sources|study|studies|paper|papers|report|reports
          |trial|trials|prior\ work|published|evidence|citation|citations
          |data)\b
    | \bremains?\ to\ be\b
    | \bnever\ been\b
    | \bto\ (?:our|the)\ knowledge\b
    | \bgaps?\ in\ (?:the\ )?(?:literature|evidence|knowledge)\b
    | \bwithout\ access\ to\ a\ literature\ review\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_atomic_claims(text: str) -> list[str]:
    """Split a passage into atomic claims (sentence-level), de-noised.

    Sentences shorter than ``_MIN_CLAIM_WORDS`` words (headings, fragments) are
    dropped, as are sentences asserting an absence of prior work (see
    ``_EVIDENCE_GAP_CLAIM``), which entailment cannot assess. Order is
    preserved and duplicates removed, so the claim list is a stable, auditable
    decomposition of the source text.

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
        if _EVIDENCE_GAP_CLAIM.search(claim):
            continue
        key = claim.lower()
        if key in seen:
            continue
        seen.add(key)
        claims.append(claim)
    return claims


_ASSESSOR_DETERMINISTIC = "deterministic-v1"


# --- Support spans (provenance) ---------------------------------------------


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
