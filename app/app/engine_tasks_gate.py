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
import logging
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


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


def _per_claim_fingerprints(
    assessor_id: str,
    ordered_claims: Sequence[str],
    claim_roles: Mapping[str, str],
    passages: Sequence[Any],
) -> dict[str, str]:
    """Fingerprint each claim against only the evidence it retrieves.

    Scoped per claim rather than over the whole pool. ``assess_claim``
    shows the assessor only the top-k passages it retrieves for that claim,
    so the rest of the pool cannot change the verdict -- but hashing all of
    it meant any new article anywhere invalidated every hypothesis's cached
    gate decision, and a run that keeps retrieving evidence never reused
    one.

    Computed once per hypothesis and reused for both the whole-hypothesis
    digest and the per-claim records the drain matches against: each digest
    costs its own retrieval pass over the pool, so deriving one level from
    the other rather than recomputing matters at a few hundred claims.
    """
    from app.claim_freshness import ClaimRecord, claim_fingerprint

    return {
        claim: claim_fingerprint(
            ClaimRecord(claim, claim_roles[claim]), passages, assessor_id
        )
        for claim in ordered_claims
    }


def _permanently_unrankable(hypothesis: Any) -> bool:
    """Return whether review already excluded this idea for good.

    ``Hypothesis.is_rankable`` is false for two different reasons, and only
    one of them is this gate's to revisit. ``evidence_blocked`` is this
    gate's *own* verdict -- an idea it blocked can still change (or the
    retrieved evidence can), so it must stay reassessable, and the
    fingerprint cache above already skips it cheaply once nothing has.
    Every other blocking disposition (``inaccurate``, ``non_novel``,
    ``inaccurate_and_non_novel``, ``unsafe``) was decided once and for all
    by the initial review gate (``agents/reflection/review.py::
    _apply_initial_review_gate``), which never reverses it -- so a wave of
    provider calls over those claims buys nothing. A hypothesis currently
    ``evidence_blocked`` whose *underlying* disposition was one of these
    (recorded as ``prior_review_disposition`` the first time this gate
    blocked it) is still permanently unrankable: the block just happens to
    read ``evidence_blocked`` on top of it.
    """
    if hypothesis.is_rankable():
        return False
    if hypothesis.review_disposition != "evidence_blocked":
        return True
    from co_scientist.models import BLOCKING_REVIEW_DISPOSITIONS

    gate_history = hypothesis.enrichments.get("claim_gate") or {}
    underlying = gate_history.get("prior_review_disposition")
    return underlying in BLOCKING_REVIEW_DISPOSITIONS - {"evidence_blocked"}


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
    from app.claim_freshness import combined_fingerprint

    ordered_claims, claim_roles = _harvest_hypothesis_claims(hypothesis)
    claim_fingerprints = _per_claim_fingerprints(
        assessor_id, ordered_claims, claim_roles, passages
    )
    input_fingerprint = combined_fingerprint(
        [claim_fingerprints[claim] for claim in ordered_claims]
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
        claim_fingerprints=claim_fingerprints,
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
    # A permanently unrankable idea (initial review already barred it) is
    # skipped before even the fingerprint check -- it can never reach the
    # tournament, so nothing here would change its fate.
    hypotheses = state.get("hypotheses") or []
    plans: list[_GatePlan] = []
    skipped_unrankable = 0
    skipped_unchanged = 0
    for hypothesis in hypotheses:
        if _permanently_unrankable(hypothesis):
            skipped_unrankable += 1
            continue
        plan = _plan_hypothesis_gate(hypothesis, passages, assessor_id)
        if plan is None:
            skipped_unchanged += 1
            continue
        plans.append(plan)

    assessed = await _assess_gate_claims(plans, passages, assessor, assessor_id)
    for plan, assessments in zip(plans, assessed, strict=True):
        _apply_gate_verdict(plan, assessments, assessor_id)
    claims_assessed = sum(len(plan.claims) for plan in plans)
    logger.info(
        "claim gate pass: considered=%d skipped_unrankable=%d "
        "skipped_unchanged=%d assessed=%d claims_assessed=%d",
        len(hypotheses),
        skipped_unrankable,
        skipped_unchanged,
        len(plans),
        claims_assessed,
    )


def _entailment_calls_so_far() -> int:
    """Return the process-wide entailment judgement count."""
    from app.claim_verifier import entailment_call_count

    return entailment_call_count()


def _charge_entailment_calls(state: dict[str, Any], calls: int) -> None:
    """Fold this gate pass's entailment calls into the run's LLM budget.

    The entailment assessor calls the provider directly rather than through
    the engine's ``call_llm``, so these never reached a run's metrics --
    and grounding issues one per extracted claim per hypothesis, hundreds
    in a real run. The tier's ``max_llm_calls`` exists as a runaway
    backstop, and it was blind to the largest single source of calls.

    Counted from a process-wide total, so a delta rather than an absolute:
    several runs share the process, and only this pass's share is this
    run's to pay.
    """
    if calls <= 0:
        return
    from co_scientist.models import MetricDeltas, create_metrics_update
    from co_scientist.models_metrics import merge_metrics

    delta = create_metrics_update(deltas=MetricDeltas(llm_calls=calls))
    existing = state.get("metrics")
    state["metrics"] = merge_metrics(existing, delta) if existing else delta
