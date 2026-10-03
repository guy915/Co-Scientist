"""Claim-level grounding, entailment, and publication gating (Milestone 5)."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence

from co_scientist.llm import record_deterministic_fallback

from app.claims.assessor import (
    _DEFAULT_RETRIEVAL_TOP_K,
    SENTENCE_SPLIT,
    AssessorDraft,
    EvidencePassage,
    deterministic_assessor,
    retrieve_passages,
)
from app.claims.assessor import Assessor as Assessor
from app.claims.assessor import as_passages as as_passages
from app.claims.gate import ClaimAssessment, EntailmentLabel, SupportSpan
from app.claims.gate import GateDecision as GateDecision
from app.claims.gate import GateResult as GateResult
from app.claims.gate import publication_gate as publication_gate

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
# A citation naming the passage's *number* rather than its evidence id --
# "3", "[3]", "(3)", "passage 3". The entailment prompt renders every
# passage as "[<n>] <text>" (claims.verifier._render_passages) and asks for
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
    if (label.is_supporting and not supporting) or (
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
    *,
    cites_evidence_ids: bool = False,
) -> dict[str, list[EvidencePassage]]:
    """Map cited keys to the shown passages they actually identify.

    Up to three keys per passage: its own evidence ID, that ID stripped of its
    ``#<chunk>`` suffix, and its 1-based prompt position. Model citations
    reserve numbers for positions because source IDs can also be numeric;
    internal citations use evidence IDs directly.
    A parent alias identifies all shown chunks of an article in either mode.
    """
    # Function-local: ``evidence_chunking`` imports ``app.claims.assessor``,
    # which loads this package (and so this module) first, so a top-level
    # import is a cycle whenever ``evidence_chunking`` is imported first.
    from app.evidence_chunking import parent_evidence_id

    lookup: dict[str, list[EvidencePassage]] = (
        {}
        if cites_evidence_ids
        else {
            str(position): [passage]
            for position, passage in enumerate(passages, start=1)
        }
    )
    for passage in passages:
        key = _normalize_key(passage.evidence_id)
        if cites_evidence_ids or not key.isdigit():
            lookup.setdefault(key, []).append(passage)
    exact_keys = set(lookup)
    for passage in passages:
        parent = _normalize_key(parent_evidence_id(passage.evidence_id))
        if (
            cites_evidence_ids or not parent.isdigit()
        ) and parent not in exact_keys:
            lookup.setdefault(parent, []).append(passage)
    return lookup


def _resolve_span(
    cited_key: str,
    quote: str,
    lookup: dict[str, list[EvidencePassage]],
) -> SupportSpan | None:
    """Locate a quote only in the cited passage or cited article's chunks."""
    for passage in lookup.get(_normalize_key(cited_key), []):
        span = locate_span(passage, quote)
        if span is not None:
            return span
    return None


def _locate_all(
    cited: Sequence[tuple[str, str]],
    passages: Sequence[EvidencePassage],
    *,
    cites_evidence_ids: bool = False,
) -> list[SupportSpan]:
    """Locate every ``(cited_key, quote)`` pair, dropping unlocatable ones.

    A cited key must name a shown passage or parent article in its declared
    mode. Unknown keys cannot borrow another claim's passage in a batch.

    Drops are logged because they are otherwise invisible: they surface
    only as an INSUFFICIENT verdict, indistinguishable from an assessor
    that found nothing (production run bc77950f -- see the module
    docstring).
    """
    lookup = _passage_lookup(passages, cites_evidence_ids=cites_evidence_ids)
    spans: list[SupportSpan] = []
    dropped = 0
    for evidence_id, quote in cited:
        span = _resolve_span(evidence_id, quote, lookup)
        if span is None:
            dropped += 1
        else:
            spans.append(span)
    if dropped:
        logger.warning(
            "%d cited span(s) could not be located in their cited source "
            "among %d shown passage(s); verdict unproven",
            dropped,
            len(passages),
        )
    return spans


# A batch assessor maps (claims, evidence pool) to one draft verdict per
# claim, in the same order as ``claims`` -- ``None`` at a position means the
# batch reply had no usable verdict for it (a missing/invalid index), and
# ``assess_claims_batch`` falls that one claim back to the deterministic
# assessor rather than discarding the whole group's result.
BatchAssessor = Callable[
    [Sequence[str], Sequence[EvidencePassage]],
    Sequence["AssessorDraft | None"],
]

# Cap on the evidence sent in one batched call: a hypothesis's claims can
# retrieve dozens of passages between them, and the prompt/response must
# stay bounded regardless of pool size (the same reasoning as per-claim
# retrieval's own top_k, one level up).
_BATCH_EVIDENCE_CAP = 12

# A hypothesis with more claims than this is split into two batches rather
# than one, so a single reply's length (verdict + quote per claim) cannot
# grow unbounded with an unusually claim-dense hypothesis.
_BATCH_CLAIM_SPLIT = 20


def _round_robin_by_rank(
    per_claim_candidates: Sequence[Sequence[EvidencePassage]],
) -> list[EvidencePassage]:
    """Flatten each claim's ranked candidates, interleaved by rank.

    Each claim's first pick, then everyone's second pick, and so on --
    rather than exhausting one claim's whole list before moving to the
    next -- so a later cap does not let one claim's tail starve every
    other claim's top-ranked pick.
    """
    max_rank = max((len(c) for c in per_claim_candidates), default=0)
    return [
        candidates[rank]
        for rank in range(max_rank)
        for candidates in per_claim_candidates
        if rank < len(candidates)
    ]


def _dedupe_capped(
    passages: Sequence[EvidencePassage], cap: int
) -> list[EvidencePassage]:
    """Drop repeated evidence ids, stopping once ``cap`` are kept."""
    seen: set[str] = set()
    union: list[EvidencePassage] = []
    for passage in passages:
        if passage.evidence_id in seen:
            continue
        seen.add(passage.evidence_id)
        union.append(passage)
        if len(union) >= cap:
            break
    return union


def _union_evidence(
    per_claim_candidates: Sequence[Sequence[EvidencePassage]],
    *,
    cap: int = _BATCH_EVIDENCE_CAP,
) -> list[EvidencePassage]:
    """Union every claim's retrieved passages, deduplicated and capped."""
    return _dedupe_capped(_round_robin_by_rank(per_claim_candidates), cap)


def _fallback_assessment(
    claim: str,
    candidates: Sequence[EvidencePassage],
    assessor_id: str,
) -> ClaimAssessment:
    """Assess one claim deterministically, stamped with the batch's own id.

    Matches ``assess_claim``'s own convention: a fallback verdict still
    carries the caller's ``assessor_id`` (naming which assessor was asked
    for), not the deterministic assessor's id. ``verification_method``
    separately records the deterministic path that produced the verdict.
    """
    draft = deterministic_assessor(claim, candidates)
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
        verification_method=draft.verification_method,
    )


def assess_claims_batch(
    claims: Sequence[str],
    passages: Sequence[EvidencePassage],
    *,
    batch_assessor: BatchAssessor,
    assessor_id: str,
    top_k: int = _DEFAULT_RETRIEVAL_TOP_K,
) -> list[ClaimAssessment]:
    """Assess a group's (one hypothesis's) claims in as few calls as possible.

    Retrieval stays per claim and unchanged (``retrieve_passages``); only
    the judgement is batched. Every claim's own top-k candidates are
    unioned (deduplicated, capped, priority-ordered) into one evidence
    block, then ``batch_assessor`` judges every claim against it in a
    single call. A claim the reply has no usable verdict for (missing or
    invalid index) falls back to the deterministic assessor for that claim
    alone, so one bad index cannot cost the whole group its verdicts.

    Args:
        claims: One group's (hypothesis's) atomic claims, in order.
        passages: The run's candidate evidence passages.
        batch_assessor: The batch-capable entailment assessor.
        assessor_id: Provenance id recorded on each assessment.
        top_k: Claim-specific retrieval budget (unchanged from
            :func:`app.claims.assess_claim`).

    Returns:
        The group's :class:`ClaimAssessment` objects, in ``claims`` order.
    """
    if not claims:
        return []
    if len(claims) > _BATCH_CLAIM_SPLIT:
        mid = (len(claims) + 1) // 2
        return assess_claims_batch(
            claims[:mid],
            passages,
            batch_assessor=batch_assessor,
            assessor_id=assessor_id,
            top_k=top_k,
        ) + assess_claims_batch(
            claims[mid:],
            passages,
            batch_assessor=batch_assessor,
            assessor_id=assessor_id,
            top_k=top_k,
        )
    return _assess_one_batch(
        claims,
        passages,
        batch_assessor=batch_assessor,
        assessor_id=assessor_id,
        top_k=top_k,
    )


def _assess_one_batch(
    claims: Sequence[str],
    passages: Sequence[EvidencePassage],
    *,
    batch_assessor: BatchAssessor,
    assessor_id: str,
    top_k: int,
) -> list[ClaimAssessment]:
    """Judge one already-sized group of claims in a single batched call."""
    per_claim_candidates = [
        retrieve_passages(claim, passages, top_k=top_k) for claim in claims
    ]
    union = _union_evidence(per_claim_candidates)
    if not union:
        # No claim in this group retrieved anything -- the deterministic
        # fallback would find nothing either, so skip the call entirely.
        drafts: Sequence[AssessorDraft | None] = [None] * len(claims)
    else:
        drafts = batch_assessor(claims, union)
    return [
        _assess_from_draft(
            claim,
            drafts[i] if i < len(drafts) else None,
            per_claim_candidates[i],
            union,
            assessor_id,
        )
        for i, claim in enumerate(claims)
    ]


def _assess_from_draft(
    claim: str,
    draft: AssessorDraft | None,
    own_candidates: Sequence[EvidencePassage],
    shown: Sequence[EvidencePassage],
    assessor_id: str,
) -> ClaimAssessment:
    """Turn one claim's batch draft (or its absence) into an assessment."""
    if draft is None:
        if shown and assessor_id.startswith("llm:"):
            record_deterministic_fallback(assessor_id[4:], "claim_batch")
        return _fallback_assessment(claim, own_candidates, assessor_id)
    supporting = _locate_all(
        draft.supporting, shown, cites_evidence_ids=draft.cites_evidence_ids
    )
    contradicting = _locate_all(
        draft.contradicting, shown, cites_evidence_ids=draft.cites_evidence_ids
    )
    label = _downgrade_unproven_label(draft.label, supporting, contradicting)
    return ClaimAssessment(
        claim=claim,
        label=label,
        supporting_passages=tuple(supporting),
        contradicting_passages=tuple(contradicting),
        assessor=assessor_id,
        verification_method=draft.verification_method,
    )


# --- Retrieval and the deterministic assessor -------------------------------
# The evidence passage, assessor draft, concept tokenizer, claim-specific
# retrieval, and the offline deterministic assessor were split into
# app/claims/assessor.py to keep this module within the size budget. They are
# imported back and re-exported (redundant aliases) so the names callers and
# tests use stay importable from app.claims.


# One call judging a whole hypothesis's claims (rather than one call per
# claim) was split into app/claims/batch.py to keep this module within the
# size budget. Both names are public API and re-exported here exactly as
# before -- see that module's docstring for the batching rationale.


# The entailment verdict enum, provenance support span, claim-assessment
# record, and publication gate were split into app/claims/gate.py to keep
# this module within the size budget. Same re-export treatment.


# Locating a cited quote in its passage and the anti-hallucination downgrade
# were split into app/claims/span.py to keep this module within the size
# budget; app/claims/batch.py's batched path depends on it too. The helpers
# below are used by assess_claim.


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


__all__ = [
    "Assessor",
    "AssessorDraft",
    "BatchAssessor",
    "ClaimAssessment",
    "EntailmentLabel",
    "EvidencePassage",
    "GateDecision",
    "GateResult",
    "as_passages",
    "assess_claims_batch",
    "deterministic_assessor",
    "publication_gate",
    "retrieve_passages",
]
