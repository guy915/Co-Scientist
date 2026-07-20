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
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app import store
from app.claims import (
    Assessor,
    ClaimAssessment,
    EvidencePassage,
    GateDecision,
    assess_claim,
    deterministic_assessor,
    extract_atomic_claims,
    publication_gate,
)

logger = logging.getLogger(__name__)

# How many claims are assessed at once. Sized against the provider, which
# returns twenty-four concurrent completions in the same wall clock as four,
# and kept below that so several runs finalizing together still share it
# comfortably. Unlike the durable cohort this costs no database writes --
# assessment persists nothing -- so SQLite's single writer does not bound it.
_ASSESSMENT_CONCURRENCY = 12

# Hypothesis fields whose text is decomposed into atomic claims. The statement
# and expected effect are visibly proposed idea content; mechanism stores the
# literature-grounding rationale and must remain categorical/evidence-backed.
_CLAIM_FIELD_ROLES = (
    ("statement", "speculative"),
    ("mechanism", "categorical"),
    ("expected_effect", "speculative"),
)


def _claim_records(hyp: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return atomic claims paired with their categorical/speculative role."""
    roles: dict[str, str] = {}
    ordered: list[str] = []
    for field, role in _CLAIM_FIELD_ROLES:
        for claim in extract_atomic_claims(str(hyp.get(field) or "")):
            if claim not in roles:
                ordered.append(claim)
                roles[claim] = role
            elif role == "categorical":
                # The strict role wins when identical text appears in both
                # rationale and proposed-idea fields.
                roles[claim] = role
    return [(claim, roles[claim]) for claim in ordered]


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
    return persist_grounding(
        run_id,
        assess_hypothesis_claims(
            hyps, passages, assessor=assessor, assessor_id=assessor_id
        ),
        allow_speculative=allow_speculative,
        conn=conn,
        db_path=db_path,
    )


def assess_hypothesis_claims(
    hyps: Sequence[Mapping[str, Any]],
    passages: Sequence[EvidencePassage],
    *,
    assessor: Assessor = deterministic_assessor,
    assessor_id: str = "deterministic-v1",
) -> list[tuple[str, list[tuple[ClaimAssessment, str]]]]:
    """Assess every hypothesis's claims against the evidence pool.

    Deliberately touches no database. The assessor may be an LLM, and one
    synchronous call per claim used to run inside the drain's single write
    transaction -- so the process held SQLite's one write lock across
    minutes of provider I/O and every other writer starved. Callers do this
    first, then open a transaction for ``persist_grounding``.

    Args:
        hyps: The run's hypotheses (rows/payloads with an ``id`` and claim
            text fields).
        passages: Retrieved evidence passages each claim is assessed
            against.
        assessor: The entailment assessor (deterministic by default).
        assessor_id: Provenance id recorded on each persisted edge.

    Returns:
        Per hypothesis id, its ``(assessment, role)`` pairs, in input order.
    """
    candidates = [p for p in passages if p.text]
    per_hypothesis = [
        (hyp_id, _claim_records(hyp))
        for hyp in hyps
        if (hyp_id := str(hyp.get("id") or ""))
    ]
    # Flattened so every claim in the run is in flight together rather than
    # one hypothesis at a time.
    flat = [
        (index, claim, role)
        for index, (_hyp_id, records) in enumerate(per_hypothesis)
        for claim, role in records
    ]
    if not flat:
        return [(hyp_id, []) for hyp_id, _records in per_hypothesis]

    def _assess_one(item: tuple[int, str, str]) -> ClaimAssessment:
        _index, claim, _role = item
        return assess_claim(
            claim, candidates, assessor=assessor, assessor_id=assessor_id
        )

    # Each claim is assessed independently, so overlapping them changes no
    # verdict -- only how long the phase takes. With the LLM assessor each
    # is a synchronous provider call, and run one at a time this was the
    # longest phase of a finished run. The provider is not the constraint:
    # measured on the production model, twenty-four concurrent completions
    # return in the same wall clock as four. ``map`` preserves input order.
    with ThreadPoolExecutor(
        max_workers=min(_ASSESSMENT_CONCURRENCY, len(flat))
    ) as pool:
        results = list(pool.map(_assess_one, flat))

    grouped: list[list[tuple[ClaimAssessment, str]]] = [
        [] for _ in per_hypothesis
    ]
    for (index, _claim, role), assessment in zip(flat, results, strict=True):
        grouped[index].append((assessment, role))
    return [
        (hyp_id, grouped[index])
        for index, (hyp_id, _records) in enumerate(per_hypothesis)
    ]


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
    blocked: set[str] = set()
    reason_by_id: dict[str, str] = {}
    for hyp_id, assessments in assessed:
        for assessment, role in assessments:
            store.add_claim_evidence(
                run_id,
                hyp_id,
                assessment.claim,
                assessment.label.value,
                [s.to_dict() for s in assessment.supporting_passages],
                [s.to_dict() for s in assessment.contradicting_passages],
                assessment.assessor,
                claim_role=role,
                conn=conn,
                db_path=db_path,
            )
        # Faithful publication policy is conservative: unsupported scientific
        # claims are quarantined alongside contradictions until revised or
        # grounded. Speculative prose may be retained in working memory, but it
        # cannot enter decisive ranking or the final report categorically.
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
        reason_by_id[hyp_id] = gate.reason
        if gate.decision is GateDecision.BLOCK:
            blocked.add(hyp_id)
            failed_claims = gate.contradicted_claims or tuple(
                claim
                for claim in gate.unsupported_claims
                if claim not in set(gate.speculative_claims)
            )
            if not failed_claims:
                failed_claims = gate.unsupported_claims
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
