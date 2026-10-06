from __future__ import annotations

import dataclasses
import functools
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from app.claims.gate import ClaimRole, is_speculative
from app.config import settings
from app.execution_policy import effective_execution_model

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _GatePlan:
    hypothesis: Any
    claims: tuple[str, ...]
    roles: Mapping[str, str]
    fingerprint: str
    claim_fingerprints: Mapping[str, str]
    prior_disposition: str


# Use a dedicated off-loop bridge: the process-wide thread executor already
# carries long-lived worker cohorts.
async def _assess_gate_claims(
    plans: Sequence[_GatePlan],
    passages: Sequence[Any],
    spec: Any,
) -> list[list[Any]]:
    """Gate and drain share one bounded assessment policy, preserving claim
    ordering and provenance.
    """
    from app.async_bridge import run_off_loop
    from app.claims.grounding import assess_claim_groups
    from app.engine_adapter import offline_mode

    call = functools.partial(
        assess_claim_groups,
        [list(plan.claims) for plan in plans],
        passages,
        spec,
    )
    if offline_mode():
        return call(parallel=False)
    return await run_off_loop(call)


def _build_evidence_passages(state: dict[str, Any]) -> list[Any]:
    """Full text is chunked for passage-specific grounding; title and
    abstract retain their single evidence span.
    """
    from app.claims import EvidencePassage
    from app.evidence_chunking import chunk_evidence_passage

    passages: list[EvidencePassage] = []
    for article in state.get("articles") or []:
        head_text = " ".join(part for part in (article.title, article.abstract) if part)
        passages.extend(
            chunk_evidence_passage(
                str(article.source_id or article.title),
                head_text=head_text,
                body_text=str(article.content or ""),
                source=article.source,
                url=str(article.url or ""),
            )
        )
    # Scientist-uploaded private sources are admissible grounding evidence
    # alongside retrieved literature.
    for source in state.get("context_enrichment_sources") or []:
        data = source.get("data") or {}
        text = str(source.get("display") or data.get("excerpt") or "").strip()
        if not text:
            continue
        passages.extend(
            chunk_evidence_passage(
                str(data.get("document_id") or data.get("title") or "private"),
                head_text="",
                body_text=text,
                source=str(source.get("source_type") or "private_document"),
                url="",
            )
        )
    return passages


def _harvest_hypothesis_claims(
    hypothesis: Any,
) -> tuple[list[str], dict[str, str]]:
    from app.claims import extract_atomic_claims

    claim_roles: dict[str, str] = {}
    ordered_claims: list[str] = []
    for source_text, role in (
        (hypothesis.text, ClaimRole.SPECULATIVE.value),
        (hypothesis.literature_grounding, ClaimRole.CATEGORICAL.value),
        (hypothesis.explanation, ClaimRole.SPECULATIVE.value),
        (hypothesis.experiment, ClaimRole.SPECULATIVE.value),
    ):
        for claim in extract_atomic_claims(source_text or ""):
            if claim not in claim_roles:
                ordered_claims.append(claim)
                claim_roles[claim] = role
            elif not is_speculative(role):
                # The strict role wins when a sentence occurs under both claim
                # roles.
                claim_roles[claim] = role
    return ordered_claims, claim_roles


def _per_claim_fingerprints(
    assessor_id: str,
    ordered_claims: Sequence[str],
    claim_roles: Mapping[str, str],
    passages: Sequence[Any],
) -> dict[str, str]:
    """Only evidence shown to a claim can invalidate its cached verdict;
    reuse the same digests at both cache levels.
    """
    from app.claims.grounding import ClaimRecord, claim_fingerprint

    return {
        claim: claim_fingerprint(ClaimRecord(claim, claim_roles[claim]), passages, assessor_id)
        for claim in ordered_claims
    }


def _permanently_unrankable(hypothesis: Any) -> bool:
    """Evidence blocks remain reassessable; irreversible initial-review
    exclusions, including covered prior dispositions, do not.
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
    from app.claims import GateDecision

    gate_history = hypothesis.enrichments.get("claim_gate") or {}
    prior_disposition = str(
        gate_history.get("prior_review_disposition") or hypothesis.review_disposition or "viable"
    )
    from app.claims.grounding import combined_fingerprint

    ordered_claims, claim_roles = _harvest_hypothesis_claims(hypothesis)
    claim_fingerprints = _per_claim_fingerprints(assessor_id, ordered_claims, claim_roles, passages)
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
                # Drain reuses individual claims against a later evidence pool
                # only when their own input fingerprints match.
                "fingerprint": plan.claim_fingerprints[assessment.claim],
                "label": assessment.label.value,
                "verification_method": assessment.verification_method,
                "supporting_passages": [span.to_dict() for span in assessment.supporting_passages],
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
    """Missing support does not withhold speculative proposals;
    contradictions still block ranking and publication.
    """
    from app.claims import GateDecision, publication_gate

    hypothesis = plan.hypothesis
    gate = publication_gate(
        assessments,
        allow_speculative=True,
        explicitly_speculative_claims={
            claim for claim, role in plan.roles.items() if is_speculative(role)
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


@dataclasses.dataclass(frozen=True)
class _GateWave:
    plans: list[_GatePlan]
    considered: int
    skipped_unrankable: int
    skipped_unchanged: int


def _build_gate_wave(
    hypotheses: Sequence[Any], passages: Sequence[Any], assessor_id: str
) -> _GateWave:
    """Irreversibly excluded ideas are skipped before retrieval or provider
    work that cannot change their fate.
    """
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
    return _GateWave(plans, len(hypotheses), skipped_unrankable, skipped_unchanged)


def _log_gate_wave(wave: _GateWave, entailment_calls: int) -> None:
    """Claims assessed and physical provider calls differ under batching;
    telemetry must not substitute one for the other.
    """
    claims_assessed = sum(len(plan.claims) for plan in wave.plans)
    logger.info(
        "claim gate pass: considered=%d skipped_unrankable=%d "
        "skipped_unchanged=%d assessed=%d claims_assessed=%d "
        "entailment_calls=%d",
        wave.considered,
        wave.skipped_unrankable,
        wave.skipped_unchanged,
        len(wave.plans),
        claims_assessed,
        entailment_calls,
    )


async def _apply_pre_ranking_evidence_gate(state: dict[str, Any]) -> None:
    from co_scientist.llm import scoped_telemetry

    from app.claims.grounding import (
        AssessorSpec,
        build_assessor,
        build_batch_assessor,
    )

    passages = _build_evidence_passages(state)
    model = effective_execution_model(settings.claim_verifier_model or settings.model_name)
    assert model is not None
    assessor, assessor_id = build_assessor(model)
    entailment_calls = [0]
    batch_assessor = build_batch_assessor(model, call_counter=entailment_calls)
    spec = AssessorSpec(assessor, assessor_id, batch_assessor)
    wave = _build_gate_wave(state.get("hypotheses") or [], passages, assessor_id)

    with scoped_telemetry("claim_gate") as telemetry:
        assessed = await _assess_gate_claims(wave.plans, passages, spec)
    for plan, assessments in zip(wave.plans, assessed, strict=True):
        _apply_gate_verdict(plan, assessments, assessor_id)
    _fold_gate_telemetry(state, telemetry.snapshot())
    _log_gate_wave(wave, entailment_calls[0])


def _fold_gate_telemetry(state: dict[str, Any], usage: Mapping[str, Mapping[str, Any]]) -> None:
    if not usage:
        return
    from co_scientist.models import MetricDeltas, create_metrics_update
    from co_scientist.models.metrics import merge_metrics

    calls = sum(entry.get("calls", 0) for entry in usage.values())
    delta = create_metrics_update(deltas=MetricDeltas(llm_calls=calls), model_usage=dict(usage))
    existing = state.get("metrics")
    state["metrics"] = merge_metrics(existing, delta) if existing else delta
