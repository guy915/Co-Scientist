"""Pre-ranking evidence gate for durable engine runs.

Extracts every pending hypothesis's atomic claims, assesses them against
the run's evidence passages in one bounded wave, and quarantines
contradicted ideas (``evidence_blocked``) before a decisive Elo
tournament. Split from ``app.engine_tasks``, which re-exports these
names for compatibility.
"""

from __future__ import annotations

import dataclasses
import functools
import logging
from collections.abc import Mapping, Sequence
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
# runs off this coroutine's event loop (``async_bridge.run_off_loop``)
# rather than on it, and rather than the default ``asyncio.to_thread``
# executor: that executor is shared process-wide and the durable worker
# cohort parks long-lived calls there for a whole run, so a wave of claims
# would contend with the workers themselves.
async def _assess_gate_claims(
    plans: Sequence[_GatePlan],
    passages: Sequence[Any],
    spec: Any,
) -> list[list[Any]]:
    """Assess every pending hypothesis's claims in one bounded wave.

    The wave policy itself (flatten, bounded pool, regroup in order) is
    ``claim_grounding.assess_claim_groups``, shared with the drain's
    grounding pass so the two claim-assessment paths cannot drift.

    Args:
        plans: The hypotheses whose claims need assessing, in state order.
        passages: Candidate evidence passages every claim is assessed
            against.
        spec: Which assessor to run (and its batch-capable counterpart, if
            any) plus the provenance id recorded on each assessment.

    Returns:
        Per plan, its claim assessments in the plan's own claim order.
    """
    from app.async_bridge import run_off_loop
    from app.claim_grounding import assess_claim_groups

    call = functools.partial(
        assess_claim_groups,
        [list(plan.claims) for plan in plans],
        passages,
        spec,
    )
    if settings.claim_assessor != "llm":
        # The deterministic assessor makes no call to overlap.
        return call(parallel=False)
    return await run_off_loop(call)


def _build_evidence_passages(state: dict[str, Any]) -> list[Any]:
    """Build the run's evidence passages from retrieved and private sources.

    Each article's fetched full text (``article.content``, up to
    ``PROMPT_PAPER_MAX_CHARS``) is chunked to passage size rather than
    kept as one whole-article passage -- see ``app.evidence_chunking`` for
    why. The title + abstract stays one chunk; only the full text, when
    present, is split into several.
    """
    from app.claims import EvidencePassage
    from app.evidence_chunking import chunk_evidence_passage

    passages: list[EvidencePassage] = []
    for article in state.get("articles") or []:
        head_text = " ".join(
            part for part in (article.title, article.abstract) if part
        )
        passages.extend(
            chunk_evidence_passage(
                str(article.source_id or article.title),
                head_text=head_text,
                body_text=str(article.content or ""),
                source=article.source,
                url=str(article.url or ""),
            )
        )
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


@dataclasses.dataclass(frozen=True)
class _GateWave:
    """One pass's plans, paired with the counts its log line reports."""

    plans: list[_GatePlan]
    considered: int
    skipped_unrankable: int
    skipped_unchanged: int


def _build_gate_wave(
    hypotheses: Sequence[Any], passages: Sequence[Any], assessor_id: str
) -> _GateWave:
    """Plan every hypothesis without a single provider call.

    A permanently unrankable idea (initial review already barred it) is
    skipped before even the fingerprint check -- it can never reach the
    tournament, so nothing here would change its fate.
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
    return _GateWave(
        plans, len(hypotheses), skipped_unrankable, skipped_unchanged
    )


def _log_gate_wave(wave: _GateWave, entailment_calls: int) -> None:
    """Log one INFO line summarizing a gate pass's counts.

    ``entailment_calls`` is the number of actual provider calls the pass
    spent, not ``claims_assessed`` -- under the batch path one call judges
    a whole hypothesis's claims (see ``app.claims.assess_claims_batch``),
    so the two diverge exactly to show the batching win: a production
    ultra run measured 218 claims assessed across 13 hypotheses one claim
    at a time; batched, the same pass costs 13 calls (or up to 26 if a
    hypothesis's claim count forces a split).
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
    """Quarantine ungrounded ideas before a decisive Elo tournament."""
    from co_scientist.llm_telemetry import scoped_telemetry

    from app.claim_grounding import (
        AssessorSpec,
        build_assessor,
        build_batch_assessor,
    )

    passages = _build_evidence_passages(state)
    model = settings.claim_verifier_model or settings.model_name
    assessor, assessor_id = build_assessor(settings.claim_assessor, model)
    entailment_calls = [0]
    batch_assessor = build_batch_assessor(
        settings.claim_assessor, model, call_counter=entailment_calls
    )
    spec = AssessorSpec(assessor, assessor_id, batch_assessor)
    wave = _build_gate_wave(
        state.get("hypotheses") or [], passages, assessor_id
    )

    with scoped_telemetry("claim_gate") as telemetry:
        assessed = await _assess_gate_claims(wave.plans, passages, spec)
    for plan, assessments in zip(wave.plans, assessed, strict=True):
        _apply_gate_verdict(plan, assessments, assessor_id)
    _fold_gate_telemetry(state, telemetry.snapshot())
    _log_gate_wave(wave, entailment_calls[0])


def _fold_gate_telemetry(
    state: dict[str, Any], usage: Mapping[str, Mapping[str, Any]]
) -> None:
    """Fold this gate pass's LLM telemetry into the run's live metrics.

    Entailment calls now run through the engine's ``call_llm_json`` seam
    (``app.claim_verifier``), so ``scoped_telemetry("claim_gate")`` above
    already captured their tokens/cost/call count -- this replaces the old
    call-count-only charge (``_charge_entailment_calls``), which existed
    only because those calls used to bypass the engine's telemetry
    entirely. A no-op when the pass made no calls (a fully-reused or
    fully-skipped pass), so it never manufactures a metrics key.
    """
    if not usage:
        return
    from co_scientist.models import MetricDeltas, create_metrics_update
    from co_scientist.models_metrics import merge_metrics

    calls = sum(entry.get("calls", 0) for entry in usage.values())
    delta = create_metrics_update(
        deltas=MetricDeltas(llm_calls=calls), model_usage=dict(usage)
    )
    existing = state.get("metrics")
    state["metrics"] = merge_metrics(existing, delta) if existing else delta
