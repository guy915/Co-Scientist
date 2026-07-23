"""Claim-level grounding wiring for the pipeline (Milestone 5 / M9).

The claim-level primitives live in :mod:`app.claims` (pure: atomic-claim
extraction, per-claim entailment, and the publication gate). This module is the
store-aware wiring both providers share (SSR §6, §7; RGV §4, §5):

1. For each hypothesis, extract atomic claims from its statement/mechanism/
   expected-effect text.
2. Assess each claim against the run's retrieved evidence passages and persist
   the resulting edge (label + exact supporting/contradicting passages +
   assessor provenance) to the ``claim_evidence`` graph.
3. Run the publication gate: a hypothesis with a contradicted or unsupported
   material claim cannot rank or publish and is quarantined for revision.

The default assessor is deterministic so the pipeline runs offline; a real
NLI/LLM entailment model is a swappable, provenance-tagged assessor.

Step 2's assessment half lives in :mod:`app.claim_grounding_assess`, which
touches no database at all -- the module boundary is what keeps a provider
call out of a write transaction. Every name it defines is re-exported here,
so ``app.claim_grounding`` remains the single import and monkeypatch
surface it has always been.
"""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from app import store
from app.claim_grounding_assess import (
    ASSESSMENT_CONCURRENCY as ASSESSMENT_CONCURRENCY,
)
from app.claim_grounding_assess import (
    AssessorSpec as AssessorSpec,
)
from app.claim_grounding_assess import (
    _assess_flat_claims as _assess_flat_claims,
)
from app.claim_grounding_assess import (
    _claim_records as _claim_records,
)
from app.claim_grounding_assess import (
    _per_hypothesis_claim_records as _per_hypothesis_claim_records,
)
from app.claim_grounding_assess import (
    _regroup_assessments as _regroup_assessments,
)
from app.claim_grounding_assess import (
    _zip_hypothesis_assessments as _zip_hypothesis_assessments,
)
from app.claim_grounding_assess import (
    assess_claim_groups as assess_claim_groups,
)
from app.claim_grounding_assess import (
    assess_hypothesis_claims as assess_hypothesis_claims,
)
from app.claims import (
    Assessor,
    ClaimAssessment,
    EvidencePassage,
    GateDecision,
    GateResult,
    deterministic_assessor,
    publication_gate,
)

logger = logging.getLogger(__name__)


def build_assessor(mode: str, model: str) -> tuple[Assessor, str]:
    """Return the ``(assessor, assessor_id)`` for a grounding mode.

    ``mode == "llm"`` builds the semantic NLI assessor (imported lazily so the
    deterministic default never pulls in the LLM path); anything else is the
    offline deterministic assessor. Used by the engine drain to honor
    ``settings.claim_assessor``.
    """
    if mode == "llm":
        from app.claim_verifier import make_llm_assessor

        return make_llm_assessor(model)
    return deterministic_assessor, "deterministic-v1"


def evidence_passages(
    run_id: str,
    *,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> list[EvidencePassage]:
    """Return the run's evidence passages (with provenance) for grounding.

    Each passage is the evidence row's title + abstract, carrying the source
    evidence id, source, and url so a support span located inside it can be
    traced back to (and opened at) its exact source. Shared by both providers
    (the mock stages pass ``db_path``; the engine drain reuses its ``conn``).
    """
    passages: list[EvidencePassage] = []
    for ev in store.list_evidence(run_id, conn=conn, db_path=db_path):
        if not ev.get("available"):
            continue
        text = " ".join(
            str(ev.get(k) or "") for k in ("title", "abstract")
        ).strip()
        if not text:
            continue
        passages.append(
            EvidencePassage(
                evidence_id=str(ev.get("id") or ""),
                text=text,
                source=str(ev.get("source") or ""),
                url=str(ev.get("url") or ""),
            )
        )
    return passages


@dataclasses.dataclass(frozen=True)
class GroundingResult:
    """Outcome of grounding a run's hypotheses against its evidence."""

    # Store ids of hypotheses a contradicted claim blocks from ranking.
    blocked_ids: frozenset[str]
    # Store id -> publication-gate reason for every grounded hypothesis.
    reason_by_id: Mapping[str, str]

    @property
    def blocked_count(self) -> int:
        """Number of hypotheses blocked by a contradicted claim."""
        return len(self.blocked_ids)


@dataclasses.dataclass(frozen=True)
class GroundingTarget:
    """Where a grounding pass persists, and how leniently it gates.

    Deliberately separate from :class:`AssessorSpec`: the provider half of
    the pipeline must never travel with the database half, because
    assessment has to finish before a write transaction opens.

    Attributes:
        allow_speculative: Gate leniency switch; the drain leaves this False.
        conn: Optional open connection to reuse (from ``transaction``).
        db_path: Optional override for the SQLite database path.
    """

    allow_speculative: bool = False
    conn: sqlite3.Connection | None = None
    db_path: str | None = None


def ground_hypotheses(
    run_id: str,
    hyps: Sequence[Mapping[str, Any]],
    passages: Sequence[EvidencePassage],
    *,
    assessment: AssessorSpec | None = None,
    target: GroundingTarget | None = None,
) -> GroundingResult:
    """Ground each hypothesis's claims, persist the graph, and gate publishing.

    Extracts atomic claims, assesses each against evidence passages (via the
    swappable assessor), persists the claim-evidence edges, and runs the
    publication gate. A hypothesis whose gate blocks because a claim is
    contradicted is returned in ``blocked_ids``, out of ranking/synthesis.

    Args:
        run_id: Identifier of the run being grounded.
        hyps: The run's hypotheses (store rows/payloads with claim text).
        passages: The run's retrieved evidence passages (with provenance).
        assessment: The assessor to run; deterministic when omitted.
        target: Where to persist and how to gate; defaults to the shared
            database with speculation disallowed.

    Returns:
        The :class:`GroundingResult` with blocked ids and per-id reasons.
    """
    assessment = assessment or AssessorSpec()
    target = target or GroundingTarget()
    return persist_grounding(
        run_id,
        assess_hypothesis_claims(
            hyps,
            passages,
            assessor=assessment.assessor,
            assessor_id=assessment.assessor_id,
        ),
        allow_speculative=target.allow_speculative,
        conn=target.conn,
        db_path=target.db_path,
    )


def persist_grounding(
    run_id: str,
    assessed: Sequence[tuple[str, list[tuple[ClaimAssessment, str]]]],
    *,
    allow_speculative: bool = False,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> GroundingResult:
    """Persist assessed claims and run each hypothesis's publication gate.

    Pure database work, so it is safe to hold a transaction across.

    Args:
        run_id: Identifier of the run being grounded.
        assessed: Output of :func:`assess_hypothesis_claims`.
        allow_speculative: Compatibility-only switch for explicitly marked
            mock workflows. Faithful engine runs must leave this False.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
        db_path: Optional override for the SQLite database path.

    Returns:
        A :class:`GroundingResult` with the blocked ids and per-id reasons.
    """
    target = GroundingTarget(
        allow_speculative=allow_speculative, conn=conn, db_path=db_path
    )
    blocked: set[str] = set()
    reason_by_id: dict[str, str] = {}
    for hyp_id, assessments in assessed:
        gate = _ground_one_hypothesis(run_id, hyp_id, assessments, target)
        reason_by_id[hyp_id] = gate.reason
        if gate.decision is GateDecision.BLOCK:
            blocked.add(hyp_id)
    return GroundingResult(
        blocked_ids=frozenset(blocked), reason_by_id=reason_by_id
    )


def _ground_one_hypothesis(
    run_id: str,
    hyp_id: str,
    assessments: list[tuple[ClaimAssessment, str]],
    target: GroundingTarget,
) -> GateResult:
    """Persist one hypothesis's claim edges, gate it, and record if blocked.

    Faithful publication policy is conservative: unsupported scientific
    claims are quarantined alongside contradictions until revised or
    grounded. Speculative prose may be retained in working memory, but it
    cannot enter decisive ranking or the final report categorically.
    """
    allow_speculative = target.allow_speculative
    _persist_claim_edges(
        run_id,
        hyp_id,
        assessments,
        conn=target.conn,
        db_path=target.db_path,
    )
    gate = publication_gate(
        [assessment for assessment, _role in assessments],
        allow_speculative=allow_speculative,
        explicitly_speculative_claims={
            assessment.claim
            for assessment, role in assessments
            if role == "speculative"
        },
        require_supported_claim=not allow_speculative,
    )
    if gate.decision is GateDecision.BLOCK:
        _record_blocked_hypothesis(
            run_id, hyp_id, gate, conn=target.conn, db_path=target.db_path
        )
    return gate


def _persist_claim_edges(
    run_id: str,
    hyp_id: str,
    assessments: list[tuple[ClaimAssessment, str]],
    *,
    conn: sqlite3.Connection | None,
    db_path: str | None,
) -> None:
    """Persist a hypothesis's assessed claims as claim_evidence edges."""
    for assessment, role in assessments:
        store.add_claim_evidence(
            store.NewClaimEvidence(
                run_id=run_id,
                hypothesis_id=hyp_id,
                claim=assessment.claim,
                label=assessment.label.value,
                supporting=[
                    s.to_dict() for s in assessment.supporting_passages
                ],
                contradicting=[
                    s.to_dict() for s in assessment.contradicting_passages
                ],
                assessor=assessment.assessor,
                claim_role=role,
            ),
            db_path=db_path,
            conn=conn,
        )


def _record_blocked_hypothesis(
    run_id: str,
    hyp_id: str,
    gate: GateResult,
    *,
    conn: sqlite3.Connection | None,
    db_path: str | None,
) -> None:
    """Persist the block decision and log the quarantine of a hypothesis."""
    failed_claims = gate.contradicted_claims or tuple(
        claim
        for claim in gate.unsupported_claims
        if claim not in set(gate.speculative_claims)
    )
    if not failed_claims:
        failed_claims = gate.unsupported_claims
    store.add_safety_decision(
        store.NewSafetyDecision(
            run_id=run_id,
            stage="claim_gate",
            decision="block",
            reason=f"hypothesis {hyp_id}: {gate.reason}",
            matches=list(failed_claims),
        ),
        db_path=db_path,
        conn=conn,
    )
    logger.warning(
        "Quarantining hypothesis %s from ranking and publication: %s",
        hyp_id,
        gate.reason,
    )
