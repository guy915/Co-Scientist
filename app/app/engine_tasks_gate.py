"""Pre-ranking evidence gate for durable engine runs.

Extracts every pending hypothesis's atomic claims, assesses them against
the run's evidence passages in one bounded wave, and quarantines
contradicted ideas (``evidence_blocked``) before a decisive Elo
tournament. Split from ``app.engine_tasks``, which re-exports these
names for compatibility.
"""

from __future__ import annotations

import asyncio
import dataclasses
import functools
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.config import settings


@dataclasses.dataclass(frozen=True)
class _GatePlan:
    """One hypothesis's extracted claims awaiting assessment.

    Built before any provider call so the whole run's claims can be assessed
    in a single wave, then paired back up with its hypothesis to apply the
    publication gate.
    """

    hypothesis: Any
    claims: tuple[str, ...]
    roles: Mapping[str, str]
    fingerprint: str
    claim_fingerprints: Mapping[str, str]
    prior_disposition: str


# In production a hypothesis carries 7-25 atomic claims and a run reaches
# this gate with dozens, and awaiting them one at a time made this node the
# longest serial stretch of an express run (21-23% of wall clock). The wave
# below runs on one dedicated thread rather than ``asyncio.to_thread``: the
# default executor is shared process-wide and the durable worker cohort
# parks long-lived calls there for a whole run, so a wave of claims would
# contend with the workers themselves.
async def _assess_gate_claims(
    plans: Sequence[_GatePlan],
    passages: Sequence[Any],
    assessor: Any,
    assessor_id: str,
) -> list[list[Any]]:
    """Assess every pending hypothesis's claims in one bounded wave.

    The wave policy itself (flatten, bounded pool, regroup in order) is
    ``claim_grounding.assess_claim_groups``, shared with the drain's
    grounding pass so the two claim-assessment paths cannot drift.

    Args:
        plans: The hypotheses whose claims need assessing, in state order.
        passages: Candidate evidence passages every claim is assessed
            against.
        assessor: The entailment assessor.
        assessor_id: Provenance id recorded on each assessment.

    Returns:
        Per plan, its claim assessments in the plan's own claim order.
    """
    from app.claim_grounding import assess_claim_groups

    call = functools.partial(
        assess_claim_groups,
        [list(plan.claims) for plan in plans],
        passages,
        assessor=assessor,
        assessor_id=assessor_id,
    )
    if settings.claim_assessor != "llm":
        # The deterministic assessor makes no call to overlap.
        return call(parallel=False)
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as host:
        return await loop.run_in_executor(host, call)


def _build_evidence_passages(state: dict[str, Any]) -> list[Any]:
    """Build the run's evidence passages from retrieved and private sources."""
    from app.claims import EvidencePassage

    passages = [
        EvidencePassage(
            evidence_id=str(article.source_id or article.title),
            text=" ".join(
                part
                for part in (article.title, article.abstract, article.content)
                if part
            ),
            source=article.source,
            url=str(article.url or ""),
        )
        for article in state.get("articles") or []
    ]
    # The scientist's private corpus is admissible evidence: a hypothesis's
    # claims may be grounded in the uploaded documents, not only in retrieved
    # literature. Including these passages lets scientist-provided evidence
    # release an otherwise-unsupported idea, matching the disclosed
    # private-repository behavior. Additive (empty when nothing was uploaded).
    for source in state.get("context_enrichment_sources") or []:
        data = source.get("data") or {}
        text = str(source.get("display") or data.get("excerpt") or "").strip()
        if not text:
            continue
        passages.append(
            EvidencePassage(
                evidence_id=str(
                    data.get("document_id") or data.get("title") or "private"
                ),
                text=text,
                source=str(source.get("source_type") or "private_document"),
                url="",
            )
        )
    return passages


def _harvest_hypothesis_claims(
    hypothesis: Any,
) -> tuple[list[str], dict[str, str]]:
    """Extract one hypothesis's atomic claims in stable order, with roles."""
    from app.claims import extract_atomic_claims

    claim_roles: dict[str, str] = {}
    ordered_claims: list[str] = []
    for source_text, role in (
        (hypothesis.text, "speculative"),
        (hypothesis.literature_grounding, "categorical"),
        (hypothesis.explanation, "speculative"),
        (hypothesis.experiment, "speculative"),
    ):
        for claim in extract_atomic_claims(source_text or ""):
            if claim not in claim_roles:
                ordered_claims.append(claim)
                claim_roles[claim] = role
            elif role == "categorical":
                claim_roles[claim] = role
    return ordered_claims, claim_roles


def _gate_input_fingerprint(
    assessor_id: str,
    ordered_claims: Sequence[str],
    claim_roles: Mapping[str, str],
    passages: Sequence[Any],
) -> str:
    """Hash one hypothesis's claims and the evidence each one retrieves.

    Scoped per claim rather than over the whole pool. ``assess_claim``
    shows the assessor only the top-k passages it retrieves for that claim,
    so the rest of the pool cannot change the verdict -- but hashing all of
    it meant any new article anywhere invalidated every hypothesis's cached
    gate decision, and a run that keeps retrieving evidence never reused
    one.
    """
    from app.claim_freshness import ClaimRecord, claims_fingerprint

    return claims_fingerprint(
        [ClaimRecord(claim, claim_roles[claim]) for claim in ordered_claims],
        passages,
        assessor_id,
    )


def _per_claim_fingerprints(
    assessor_id: str,
    ordered_claims: Sequence[str],
    claim_roles: Mapping[str, str],
    passages: Sequence[Any],
) -> dict[str, str]:
    """Fingerprint each claim on its own, for the drain to match against."""
    from app.claim_freshness import ClaimRecord, claim_fingerprint

    return {
        claim: claim_fingerprint(
            ClaimRecord(claim, claim_roles[claim]), passages, assessor_id
        )
        for claim in ordered_claims
    }


def _plan_hypothesis_gate(
    hypothesis: Any,
    passages: Sequence[Any],
    assessor_id: str,
) -> _GatePlan | None:
    """Extract one hypothesis's claims, or apply its cached verdict.

    Returns ``None`` when an unchanged proposal/evidence snapshot lets the
    hypothesis reuse its already-audited decision (applied here directly)
    instead of spending compute reassessing claims nothing changed about.
    """
    from app.claims import GateDecision

    gate_history = hypothesis.enrichments.get("claim_gate") or {}
    prior_disposition = str(
        gate_history.get("prior_review_disposition")
        or hypothesis.review_disposition
        or "viable"
    )
    ordered_claims, claim_roles = _harvest_hypothesis_claims(hypothesis)
    input_fingerprint = _gate_input_fingerprint(
        assessor_id, ordered_claims, claim_roles, passages
    )
    if gate_history.get("input_fingerprint") == input_fingerprint:
        if gate_history.get("decision") == GateDecision.BLOCK.value:
            hypothesis.review_disposition = "evidence_blocked"
        elif hypothesis.review_disposition == "evidence_blocked":
            hypothesis.review_disposition = prior_disposition
        return None
    return _GatePlan(
        hypothesis=hypothesis,
        claims=tuple(ordered_claims),
        roles=claim_roles,
        fingerprint=input_fingerprint,
        claim_fingerprints=_per_claim_fingerprints(
            assessor_id, ordered_claims, claim_roles, passages
        ),
        prior_disposition=prior_disposition,
    )


def _record_gate_enrichment(
    hypothesis: Any,
    plan: _GatePlan,
    assessments: list[Any],
    gate: Any,
    assessor_id: str,
) -> None:
    """Record one hypothesis's audited claim-gate verdict for reuse/audit."""
    plan_roles = plan.roles
    hypothesis.enrichments["claim_gate"] = {
        "decision": gate.decision.value,
        "reason": gate.reason,
        "assessor": assessor_id,
        "input_fingerprint": plan.fingerprint,
        "prior_review_disposition": plan.prior_disposition,
        "claims": [
            {
                "claim": assessment.claim,
                "role": plan_roles[assessment.claim],
                # Per claim, not just per hypothesis: the drain assesses a
                # subset of these claims against a later evidence pool, and
                # reuses each verdict whose own inputs still match.
                "fingerprint": plan.claim_fingerprints[assessment.claim],
                "label": assessment.label.value,
                "supporting_passages": [
                    span.to_dict() for span in assessment.supporting_passages
                ],
                "contradicting_passages": [
                    span.to_dict() for span in assessment.contradicting_passages
                ],
            }
            for assessment in assessments
        ],
    }


def _apply_gate_verdict(
    plan: _GatePlan,
    assessments: list[Any],
    assessor_id: str,
) -> None:
    """Apply one hypothesis's publication-gate verdict to its state.

    Rank-and-publish policy: only contradicted (or unsafe) ideas are
    withheld from the tournament here. Ungrounded/speculative ideas stay
    rankable -- allow_speculative treats insufficient claims as speculative
    and require_supported_claim=False drops the "needs a supported claim"
    block -- so every non-contradicted idea earns an Elo score and can be
    published (badged unverified) instead of blocking the whole run.
    """
    from app.claims import GateDecision, publication_gate

    hypothesis = plan.hypothesis
    gate = publication_gate(
        assessments,
        allow_speculative=True,
        explicitly_speculative_claims={
            claim for claim, role in plan.roles.items() if role == "speculative"
        },
        require_supported_claim=False,
    )
    _record_gate_enrichment(hypothesis, plan, assessments, gate, assessor_id)
    if gate.decision is GateDecision.BLOCK:
        hypothesis.review_disposition = "evidence_blocked"
        feedback = f"Evidence gate: {gate.reason}"
        if feedback not in (hypothesis.reflection_notes or ""):
            hypothesis.reflection_notes = "\n".join(
                part for part in (hypothesis.reflection_notes, feedback) if part
            )
    elif hypothesis.review_disposition == "evidence_blocked":
        hypothesis.review_disposition = plan.prior_disposition


async def _apply_pre_ranking_evidence_gate(state: dict[str, Any]) -> None:
    """Quarantine ungrounded ideas before a decisive Elo tournament."""
    from app.claim_grounding import build_assessor

    passages = _build_evidence_passages(state)
    assessor, assessor_id = build_assessor(
        settings.claim_assessor,
        settings.claim_verifier_model or settings.model_name,
    )
    # Pass one plans every hypothesis without making a single provider call,
    # so the claims that actually need assessing can go out together below.
    plans: list[_GatePlan] = []
    for hypothesis in state.get("hypotheses") or []:
        plan = _plan_hypothesis_gate(hypothesis, passages, assessor_id)
        if plan is not None:
            plans.append(plan)

    assessed = await _assess_gate_claims(plans, passages, assessor, assessor_id)
    for plan, assessments in zip(plans, assessed, strict=True):
        _apply_gate_verdict(plan, assessments, assessor_id)
