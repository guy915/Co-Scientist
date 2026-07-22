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
import hashlib
import json
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
    prior_disposition: str


async def _assess_gate_claims(
    plans: Sequence[_GatePlan],
    passages: Sequence[Any],
    assessor: Any,
    assessor_id: str,
) -> list[list[Any]]:
    """Assess every pending hypothesis's claims in one bounded wave.

    In production a hypothesis carries 7-25 atomic claims and a run reaches
    this gate with dozens, and awaiting them one at a time made this node the
    longest serial stretch of an express run (21-23% of wall clock). The wave
    policy itself (flatten, bounded pool, regroup in order) is
    ``claim_grounding.assess_claim_groups``, shared with the drain's grounding
    pass so the two claim-assessment paths cannot drift.

    The wave runs on one dedicated thread rather than ``asyncio.to_thread``:
    the default executor is shared process-wide and the durable worker cohort
    parks long-lived calls there for a whole run, so a wave of claims would
    contend with the workers themselves.

    Args:
        plans: The hypotheses whose claims need assessing, in state order.
        passages: Candidate evidence passages every claim is assessed against.
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


async def _apply_pre_ranking_evidence_gate(state: dict[str, Any]) -> None:
    """Quarantine ungrounded ideas before a decisive Elo tournament."""
    from app.claim_grounding import build_assessor
    from app.claims import (
        EvidencePassage,
        GateDecision,
        extract_atomic_claims,
        publication_gate,
    )

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
    assessor, assessor_id = build_assessor(
        settings.claim_assessor,
        settings.claim_verifier_model or settings.model_name,
    )
    # Pass one plans every hypothesis without making a single provider call,
    # so the claims that actually need assessing can go out together below.
    plans: list[_GatePlan] = []
    for hypothesis in state.get("hypotheses") or []:
        gate_history = hypothesis.enrichments.get("claim_gate") or {}
        prior_disposition = str(
            gate_history.get("prior_review_disposition")
            or hypothesis.review_disposition
            or "viable"
        )
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
        input_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "assessor": assessor_id,
                    "claims": [
                        [claim, claim_roles[claim]] for claim in ordered_claims
                    ],
                    "passages": [
                        {
                            "evidence_id": passage.evidence_id,
                            "text": passage.text,
                            "source": passage.source,
                            "url": passage.url,
                        }
                        for passage in passages
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        # An unchanged proposal/evidence snapshot reuses its audited verdict;
        # repeated ranking cycles should spend compute on new science.
        if gate_history.get("input_fingerprint") == input_fingerprint:
            if gate_history.get("decision") == GateDecision.BLOCK.value:
                hypothesis.review_disposition = "evidence_blocked"
            elif hypothesis.review_disposition == "evidence_blocked":
                hypothesis.review_disposition = prior_disposition
            continue
        plans.append(
            _GatePlan(
                hypothesis=hypothesis,
                claims=tuple(ordered_claims),
                roles=claim_roles,
                fingerprint=input_fingerprint,
                prior_disposition=prior_disposition,
            )
        )

    assessed = await _assess_gate_claims(plans, passages, assessor, assessor_id)

    for plan, assessments in zip(plans, assessed, strict=True):
        hypothesis = plan.hypothesis
        plan_roles = plan.roles
        input_fingerprint = plan.fingerprint
        prior_disposition = plan.prior_disposition
        # Rank-and-publish policy: only contradicted (or unsafe) ideas are
        # withheld from the tournament here. Ungrounded/speculative ideas stay
        # rankable — allow_speculative treats insufficient claims as speculative
        # and require_supported_claim=False drops the "needs a supported claim"
        # block — so every non-contradicted idea earns an Elo score and can be
        # published (badged unverified) instead of blocking the whole run.
        gate = publication_gate(
            assessments,
            allow_speculative=True,
            explicitly_speculative_claims={
                claim
                for claim, role in plan_roles.items()
                if role == "speculative"
            },
            require_supported_claim=False,
        )
        hypothesis.enrichments["claim_gate"] = {
            "decision": gate.decision.value,
            "reason": gate.reason,
            "assessor": assessor_id,
            "input_fingerprint": input_fingerprint,
            "prior_review_disposition": prior_disposition,
            "claims": [
                {
                    "claim": assessment.claim,
                    "role": plan_roles[assessment.claim],
                    "label": assessment.label.value,
                    "supporting_passages": [
                        span.to_dict()
                        for span in assessment.supporting_passages
                    ],
                    "contradicting_passages": [
                        span.to_dict()
                        for span in assessment.contradicting_passages
                    ],
                }
                for assessment in assessments
            ],
        }
        if gate.decision is GateDecision.BLOCK:
            hypothesis.review_disposition = "evidence_blocked"
            feedback = f"Evidence gate: {gate.reason}"
            if feedback not in (hypothesis.reflection_notes or ""):
                hypothesis.reflection_notes = "\n".join(
                    part
                    for part in (hypothesis.reflection_notes, feedback)
                    if part
                )
        elif hypothesis.review_disposition == "evidence_blocked":
            hypothesis.review_disposition = prior_disposition
