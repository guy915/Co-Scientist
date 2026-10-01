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
   claim cannot ground it. A passage is passage-sized, not whole-article: a
   long article's fetched full text is split into paragraph/sentence-window
   chunks before retrieval (``app/evidence_chunking.py``), each carrying its
   parent article's id (``<article id>#<chunk index>``, recoverable via
   ``parent_evidence_id``) — see that module's docstring for why whole
   articles as "passages" made the claim gate the most expensive phase in a
   production run.
3. **Per-claim entailment** — for each claim, assess the retrieved evidence as
   SUPPORTS / CONTRADICTS / INSUFFICIENT via a swappable *assessor*, recording
   the exact supporting/contradicting **span** (source evidence id, quoted
   text, and character offsets) plus the assessor provenance. The stored span
   is what lets a displayed verified claim open its exact supporting passage;
   every reader-facing consumer of that id resolves it through
   ``parent_evidence_id`` first, since a chunked passage's span carries the
   chunk's id, not the article's. The LLM assessor judges a whole
   hypothesis's claims in one call rather than one call per claim
   (``assess_claims_batch``, ``app/claims/batch.py``) -- a production ultra
   run measured 218 claims assessed one at a time across 13 hypotheses in a
   single pass, repeated before every ranking wave.
4. **Citation metadata, separately** — whether a citation's source resolves
   (URL/DOI/PMID/retraction), what kind of source it is, and whether it
   carries a usable date are judged independently of whether it supports the
   claim (``app/citation_metadata.py``), reachability via a swappable
   *resolver* (offline metadata by default; the live URL/DOI/retraction
   lookup in ``app/citation_resolver.py`` in production).
5. **Publication gate** — an unsupported or contradicted *fundamental* claim
   cannot let a hypothesis rank/publish; clearly labeled speculation is allowed
   only under an explicit policy flag.

The default assessor is deterministic (a contradiction lexicon plus a lexical
support fallback) so the pipeline and its tests run offline. A real NLI/LLM
entailment assessor is a documented, swappable, provenance-tagged drop-in
(``app/claims/verifier.py``); it is exercised end-to-end by the golden run
rather than in the offline suite. Google does not publish its entailment model
or thresholds (SSR §12), so those are documented clone choices.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.claims.assessor import (
    _DEFAULT_RETRIEVAL_TOP_K,
    SENTENCE_SPLIT,
)

# --- Retrieval and the deterministic assessor -------------------------------
# The evidence passage, assessor draft, concept tokenizer, claim-specific
# retrieval, and the offline deterministic assessor were split into
# app/claims/assessor.py to keep this module within the size budget. They are
# imported back and re-exported (redundant aliases) so the names callers and
# tests use stay importable from app.claims.
from app.claims.assessor import (
    Assessor as Assessor,
)
from app.claims.assessor import (
    AssessorDraft as AssessorDraft,
)
from app.claims.assessor import (
    EvidencePassage as EvidencePassage,
)
from app.claims.assessor import (
    as_passages as as_passages,
)
from app.claims.assessor import (
    deterministic_assessor as deterministic_assessor,
)
from app.claims.assessor import (
    retrieve_passages as retrieve_passages,
)

# One call judging a whole hypothesis's claims (rather than one call per
# claim) was split into app/claims/batch.py to keep this module within the
# size budget. Both names are public API and re-exported here exactly as
# before -- see that module's docstring for the batching rationale.
from app.claims.batch import (
    BatchAssessor as BatchAssessor,
)
from app.claims.batch import (
    assess_claims_batch as assess_claims_batch,
)

# The entailment verdict enum, provenance support span, claim-assessment
# record, and publication gate were split into app/claims/gate.py to keep
# this module within the size budget. Same re-export treatment.
from app.claims.gate import (
    ClaimAssessment as ClaimAssessment,
)
from app.claims.gate import (
    EntailmentLabel as EntailmentLabel,
)
from app.claims.gate import (
    GateDecision as GateDecision,
)
from app.claims.gate import (
    GateResult as GateResult,
)
from app.claims.gate import (
    publication_gate as publication_gate,
)

# Locating a cited quote in its passage and the anti-hallucination downgrade
# were split into app/claims/span.py to keep this module within the size
# budget; app/claims/batch.py's batched path depends on it too. The helpers
# below are used by assess_claim.
from app.claims.span import (
    _downgrade_unproven_label,
    _locate_all,
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
#
# The alternation is inflectional, not a list of specimens: each wording a
# run produces is the same negative existential conjugated differently, so
# a branch missing one inflection ("no source" but not "did not find any
# source", "not reported" but not "unreported", "unexplored" but not
# "under-explored") lets the identical sentence through. Those three
# escapes were still reaching the gate as *categorical* claims in
# production runs bc77950f and d1273490 (2026-09-07/08).
_EVIDENCE_GAP_CLAIM = re.compile(
    r"""
      \bun(?:explored|examined|tested|studied|addressed|proven|reported
            |documented|characteri[sz]ed)\b
    | \bunder[-\ ]?(?:explored|examined|tested|studied|investigated
            |reported|documented|characteri[sz]ed)\b
    | \b(?:did|do|does)\ not\ (?:find|identify|locate|report|reveal)\b
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
    for raw in SENTENCE_SPLIT.split(text or ""):
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
    draft = assessor(claim, candidates)
    supporting = _locate_all(
        draft.supporting,
        candidates,
        cites_evidence_ids=draft.cites_evidence_ids,
    )
    contradicting = _locate_all(
        draft.contradicting,
        candidates,
        cites_evidence_ids=draft.cites_evidence_ids,
    )
    label = _downgrade_unproven_label(draft.label, supporting, contradicting)
    return ClaimAssessment(
        claim=claim,
        label=label,
        supporting_passages=tuple(supporting),
        contradicting_passages=tuple(contradicting),
        assessor=assessor_id,
        verification_method=(
            draft.verification_method if candidates else "no_evidence"
        ),
    )
