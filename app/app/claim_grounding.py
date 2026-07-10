"""Claim-level grounding wiring for the pipeline (Milestone 5 / M9).

The claim-level primitives live in :mod:`app.claims` (pure: atomic-claim
extraction, per-claim entailment, and the publication gate). This module is the
store-aware wiring both providers share (SSR §6, §7; RGV §4, §5):

1. For each hypothesis, extract atomic claims from its statement/mechanism/
   expected-effect text.
2. Assess each claim against the run's retrieved evidence passages and persist
   the resulting edge (label + exact supporting/contradicting passages +
   assessor provenance) to the ``claim_evidence`` graph.
3. Run the publication gate: a hypothesis with a *contradicted* fundamental
   claim cannot rank or publish and is excluded from the tournament and
   synthesis. Merely unsupported (insufficient) claims are recorded and
   surfaced as labeled speculation rather than hard-excluded, so they feed
   back into revision without silently deleting benign hypotheses.

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
    GateDecision,
    assess_claim,
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


def evidence_passages(
    run_id: str,
    *,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> list[str]:
    """Return the run's evidence text (title + abstract) for claim grounding.

    Shared by both providers (the mock stages pass ``db_path``; the engine
    drain reuses its open ``conn``).
    """
    passages: list[str] = []
    for ev in store.list_evidence(run_id, conn=conn, db_path=db_path):
        text = " ".join(
            str(ev.get(k) or "") for k in ("title", "abstract")
        ).strip()
        if text:
            passages.append(text)
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
    evidence_passages: Sequence[str],
    *,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> GroundingResult:
    """Ground each hypothesis's claims, persist the graph, and gate publishing.

    For every hypothesis this extracts atomic claims, assesses each against the
    run's evidence passages, persists the claim-evidence edges, and runs the
    publication gate. A hypothesis whose gate blocks *because a claim is
    contradicted* is returned in ``blocked_ids`` so the caller keeps it out of
    the tournament and synthesis.

    Args:
        run_id: Identifier of the run being grounded.
        hyps: The run's hypotheses (store rows/payloads with an ``id`` and the
            claim text fields).
        evidence_passages: The run's retrieved evidence passages (e.g. abstract
            text) every claim is assessed against.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
        db_path: Optional override for the SQLite database path.

    Returns:
        A :class:`GroundingResult` with the blocked ids and per-id reasons.
    """
    passages = [p for p in evidence_passages if p]
    blocked: set[str] = set()
    reason_by_id: dict[str, str] = {}
    for hyp in hyps:
        hyp_id = str(hyp.get("id") or "")
        if not hyp_id:
            continue
        claims = extract_atomic_claims(_claim_source_text(hyp))
        assessments = [assess_claim(claim, list(passages)) for claim in claims]
        for assessment in assessments:
            store.add_claim_evidence(
                run_id,
                hyp_id,
                assessment.claim,
                assessment.label.value,
                assessment.supporting_passages,
                assessment.contradicting_passages,
                assessment.assessor,
                conn=conn,
                db_path=db_path,
            )
        # Speculation is permitted (unsupported claims feed back to revision as
        # labeled speculation); only a contradicted fundamental claim is a hard
        # publication blocker.
        gate = publication_gate(assessments, allow_speculative=True)
        reason_by_id[hyp_id] = gate.reason
        if gate.decision is GateDecision.BLOCK and gate.contradicted_claims:
            blocked.add(hyp_id)
            store.add_safety_decision(
                run_id,
                stage="claim_gate",
                decision="block",
                reason=f"hypothesis {hyp_id}: {gate.reason}",
                matches=list(gate.contradicted_claims),
                conn=conn,
                db_path=db_path,
            )
            logger.warning(
                "Blocking hypothesis %s from the tournament: %s",
                hyp_id,
                gate.reason,
            )
    return GroundingResult(
        blocked_ids=frozenset(blocked), reason_by_id=reason_by_id
    )
