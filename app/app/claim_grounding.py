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
"""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from app import store
from app.claims import (
    Assessor,
    EvidencePassage,
    GateDecision,
    assess_claim,
    deterministic_assessor,
    extract_atomic_claims,
    publication_gate,
)

logger = logging.getLogger(__name__)

# Hypothesis fields whose text is decomposed into atomic claims.
_CLAIM_FIELDS = ("statement", "mechanism", "expected_effect")


def _claim_source_text(hyp: Mapping[str, Any]) -> str:
    """Return the combined text a hypothesis's atomic claims come from."""
    parts = [str(hyp.get(field) or "") for field in _CLAIM_FIELDS]
    return " ".join(part for part in parts if part)


def build_assessor(mode: str, model: str) -> tuple[Assessor, str]:
    """Return the ``(assessor, assessor_id)`` for a grounding mode.

    ``mode == "llm"`` builds the semantic NLI assessor (imported lazily so the
    deterministic default never pulls in the LLM path); anything else is the
    offline deterministic assessor. Used by the real-engine drain to honor
    ``settings.claim_assessor``; the mock path always grounds deterministically.
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


def ground_hypotheses(
    run_id: str,
    hyps: Sequence[Mapping[str, Any]],
    passages: Sequence[EvidencePassage],
    *,
    assessor: Assessor = deterministic_assessor,
    assessor_id: str = "deterministic-v1",
    allow_speculative: bool = False,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> GroundingResult:
    """Ground each hypothesis's claims, persist the graph, and gate publishing.

    For every hypothesis this extracts atomic claims, retrieves and assesses
    the most relevant evidence passages per claim (via the swappable
    ``assessor``), persists the claim-evidence edges with provenance-stamped
    support spans, and runs the publication gate. A hypothesis whose gate
    blocks *because a claim is contradicted* is returned in ``blocked_ids`` so
    the caller keeps it out of the tournament and synthesis.

    Args:
        run_id: Identifier of the run being grounded.
        hyps: The run's hypotheses (store rows/payloads with an ``id`` and the
            claim text fields).
        passages: The run's retrieved evidence passages (with provenance) every
            claim is assessed against.
        assessor: The entailment assessor (deterministic by default; the LLM
            assessor is plugged in for a real grounded run).
        assessor_id: Provenance id recorded on each persisted edge.
        allow_speculative: Compatibility-only switch for explicitly marked mock
            workflows. Faithful engine runs must leave this False.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
        db_path: Optional override for the SQLite database path.

    Returns:
        A :class:`GroundingResult` with the blocked ids and per-id reasons.
    """
    candidates = [p for p in passages if p.text]
    blocked: set[str] = set()
    reason_by_id: dict[str, str] = {}
    for hyp in hyps:
        hyp_id = str(hyp.get("id") or "")
        if not hyp_id:
            continue
        claims = extract_atomic_claims(_claim_source_text(hyp))
        assessments = [
            assess_claim(
                claim,
                candidates,
                assessor=assessor,
                assessor_id=assessor_id,
            )
            for claim in claims
        ]
        for assessment in assessments:
            store.add_claim_evidence(
                run_id,
                hyp_id,
                assessment.claim,
                assessment.label.value,
                [s.to_dict() for s in assessment.supporting_passages],
                [s.to_dict() for s in assessment.contradicting_passages],
                assessment.assessor,
                conn=conn,
                db_path=db_path,
            )
        # Faithful publication policy is conservative: unsupported scientific
        # claims are quarantined alongside contradictions until revised or
        # grounded. Speculative prose may be retained in working memory, but it
        # cannot enter decisive ranking or the final report categorically.
        gate = publication_gate(
            assessments, allow_speculative=allow_speculative
        )
        reason_by_id[hyp_id] = gate.reason
        if gate.decision is GateDecision.BLOCK:
            blocked.add(hyp_id)
            failed_claims = gate.contradicted_claims or gate.unsupported_claims
            store.add_safety_decision(
                run_id,
                stage="claim_gate",
                decision="block",
                reason=f"hypothesis {hyp_id}: {gate.reason}",
                matches=list(failed_claims),
                conn=conn,
                db_path=db_path,
            )
            logger.warning(
                "Quarantining hypothesis %s from ranking and publication: %s",
                hyp_id,
                gate.reason,
            )
    return GroundingResult(
        blocked_ids=frozenset(blocked), reason_by_id=reason_by_id
    )
