"""Batched entailment: judge a hypothesis's claims in as few calls as possible.

Split out of :mod:`app.claims` to keep that module within the size
budget. ``claims.assess_claim`` costs one provider call per claim -- fine
for the deterministic assessor (no call to spend), ruinous for the LLM
one: a production ultra run measured 218 claims per pass across 13
hypotheses, repeated before every ranking wave (~1,000 calls in one run).
A :data:`BatchAssessor` judges one group's (a hypothesis's) claims in a
single call instead, keyed by the claim's position rather than by echoing
its text back (see the root AGENTS.md "Structured-output schemas must not
echo input back" gotcha -- doing otherwise scales the reply with the pool
and risks the same truncation that broke proximity dedup).

Retrieval stays per claim and unchanged (``claims_assessor.retrieve_
passages``); only the judgement is batched. :mod:`app.claims` re-exports
:func:`assess_claims_batch` and :data:`BatchAssessor`, since both are
public API; this module depends on :mod:`app.claims_span` for span
location and the anti-hallucination downgrade, never on :mod:`app.claims`
itself, so the two cannot form an import cycle.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from co_scientist.llm_telemetry import record_deterministic_fallback

from app.claims_assessor import (
    _DEFAULT_RETRIEVAL_TOP_K,
    AssessorDraft,
    EvidencePassage,
    deterministic_assessor,
    retrieve_passages,
)
from app.claims_gate import ClaimAssessment
from app.claims_span import _downgrade_unproven_label, _locate_all

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
    for), not the deterministic assessor's id -- the fallback is an
    implementation detail of that assessor's best-effort contract, not a
    different provenance.
    """
    draft = deterministic_assessor(claim, candidates)
    supporting = _locate_all(draft.supporting, candidates)
    contradicting = _locate_all(draft.contradicting, candidates)
    label = _downgrade_unproven_label(draft.label, supporting, contradicting)
    return ClaimAssessment(
        claim=claim,
        label=label,
        supporting_passages=tuple(supporting),
        contradicting_passages=tuple(contradicting),
        assessor=assessor_id,
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
    supporting = _locate_all(draft.supporting, shown)
    contradicting = _locate_all(draft.contradicting, shown)
    label = _downgrade_unproven_label(draft.label, supporting, contradicting)
    return ClaimAssessment(
        claim=claim,
        label=label,
        supporting_passages=tuple(supporting),
        contradicting_passages=tuple(contradicting),
        assessor=assessor_id,
    )
