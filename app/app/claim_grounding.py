"""Claim-level grounding wiring for the pipeline (Milestone 5 / M9).

The claim-level primitives live in :mod:`app.claims` (pure: atomic-claim
extraction, per-claim entailment, and the publication gate). This module is the
store-aware wiring the engine drain runs (SSR §6, §7; RGV §4, §5):

1. For each hypothesis, extract atomic claims from its statement/mechanism/
   expected-effect text.
2. Assess each claim against the run's retrieved evidence passages and persist
   the resulting edge (label + exact supporting/contradicting passages +
   assessor provenance) to the ``claim_evidence`` graph.
3. Run the publication gate and record its verdict. A *contradicted* claim
   withholds the hypothesis from the report (the contradiction gate in
   ``report_content_gates``); a merely unsupported one does not, under the
   rank-and-publish policy -- the idea is published carrying an "Unverified"
   badge. This module records the verdict; it does not enforce it.

The default assessor is deterministic so the pipeline runs offline; a real
NLI/LLM entailment model is a swappable, provenance-tagged assessor.

Step 2's assessment half lives in :mod:`app.claim_grounding_assess`, which
touches no database at all -- the module boundary is what keeps a provider
call out of a write transaction. The names callers and tests still reach
through ``app.claim_grounding`` are re-exported here, so it remains their
import and monkeypatch surface.
"""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from app import store
from app.claim_grounding_assess import (
    AssessorSpec as AssessorSpec,
)
from app.claim_grounding_assess import (
    assess_claim_groups as assess_claim_groups,
)
from app.claim_grounding_assess import (
    assess_hypothesis_claims as assess_hypothesis_claims,
)
from app.claims import (
    _ASSESSOR_DETERMINISTIC,
    Assessor,
    BatchAssessor,
    ClaimAssessment,
    EntailmentLabel,
    EvidencePassage,
    GateDecision,
    GateResult,
    deterministic_assessor,
    publication_gate,
)

logger = logging.getLogger(__name__)

_SUPPORTING_LABELS = (EntailmentLabel.SUPPORTS, EntailmentLabel.PARTIAL)


def build_assessor(mode: str, model: str) -> tuple[Assessor, str]:
    """Return the ``(assessor, assessor_id)`` for a grounding mode.

    ``mode == "llm"`` builds the semantic NLI assessor (imported lazily so the
    deterministic default never pulls in the LLM path); anything else is the
    offline deterministic assessor. Used by the engine drain to honor
    ``settings.claim_assessor``.

    An offline process takes the deterministic assessor whatever the mode
    says. ``claim_assessor`` defaults to ``"llm"`` and this is an app-side
    call site, so it never passed through the engine's offline router: a run
    the whole system believed was offline still sent one real, billable
    provider call per claim group, using whatever credential happened to be
    in the environment. Measured at 177 calls in a single offline
    ``make parity`` run, and invisible until the account ran out of credit --
    the assessor falls back to the deterministic one on any provider error,
    so the only symptom was that a suite which had been passing began
    withholding every idea.

    This is the same class of leak the run driver's own
    ``configure_environment`` documents at another call site, which is why
    the guard belongs here, at the seam every caller shares, rather than in
    each of them.
    """
    from app.engine_adapter.provider import offline_mode

    if mode == "llm" and not offline_mode():
        from app.claim_verifier import make_llm_assessor

        return make_llm_assessor(model)
    return deterministic_assessor, _ASSESSOR_DETERMINISTIC


def build_batch_assessor(
    mode: str, model: str, *, call_counter: list[int] | None = None
) -> BatchAssessor | None:
    """Return the batch-capable assessor for a grounding mode, or None.

    Mirrors ``build_assessor``'s offline/mode guard exactly -- both gate the
    same real provider call, so a leak closed on one and left open on the
    other would just move the bill. ``None`` for the deterministic mode
    (nothing to batch: it costs no provider call to overlap) and for an
    offline process regardless of the configured mode.

    Args:
        mode: ``settings.claim_assessor``.
        model: The model to build the assessor for.
        call_counter: Forwarded to ``make_llm_batch_assessor`` -- see its
            docstring for what it counts.

    Returns:
        The batch assessor, or None when the flat per-claim path (or the
        deterministic assessor) applies instead.
    """
    from app.engine_adapter.provider import offline_mode

    if mode == "llm" and not offline_mode():
        from app.claim_verifier_batch import make_llm_batch_assessor

        batch_assessor, _ = make_llm_batch_assessor(
            model, call_counter=call_counter
        )
        return batch_assessor
    return None


def evidence_passages(
    run_id: str,
    *,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> list[EvidencePassage]:
    """Return the run's evidence passages (with provenance) for grounding.

    Each passage is the evidence row's ``passage_text`` -- title + abstract,
    materialized once at insert time (``store.records._evidence_passage_text``)
    so a support span's offsets always index the exact text stored on the
    row rather than a value reconstructed fresh on every read. Rows written
    before that column existed fall back to reconstructing it the same way,
    since their stored ``title``/``abstract`` are all that survives. Carries
    the source evidence id, source, and url so a support span located
    inside it can be traced back to (and opened at) its exact source.
    Callers pass either ``conn`` (the engine drain reuses its open
    transaction) or ``db_path``.

    Routed through ``app.evidence_chunking.chunk_evidence_passage`` for the
    same reason the pre-ranking gate is (see that module): a persisted
    evidence row never carries fetched full text (only title + abstract),
    so this is a no-op today, but it keeps the two claim-assessment paths
    sharing one chunking policy rather than letting them drift if that
    ever changes.
    """
    from app.evidence_chunking import chunk_evidence_passage

    passages: list[EvidencePassage] = []
    for ev in store.list_evidence(run_id, conn=conn, db_path=db_path):
        if not ev.get("available"):
            continue
        text = str(ev.get("passage_text") or "").strip()
        if not text:
            text = " ".join(
                str(ev.get(k) or "") for k in ("title", "abstract")
            ).strip()
        if not text:
            continue
        passages.extend(
            chunk_evidence_passage(
                str(ev.get("id") or ""),
                head_text=text,
                body_text="",
                source=str(ev.get("source") or ""),
                url=str(ev.get("url") or ""),
            )
        )
    return passages


@dataclasses.dataclass(frozen=True)
class GroundingResult:
    """Outcome of grounding a run's hypotheses against its evidence."""

    # Store ids of hypotheses that did not clear the publication gate.
    # Advisory: the report withholds only *contradicted* ideas (see
    # report_content_gates.exclude_unsafe_hypotheses) and publishes merely
    # unsupported ones with an "Unverified" badge. Nothing reads this set but
    # the count, which the run's citation.grounding event reports.
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
    publication gate. A hypothesis whose gate does not clear is returned in
    ``blocked_ids``; see that field for what does and does not follow from it.

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
        assess_hypothesis_claims(hyps, passages, assessment),
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
        allow_speculative: Compatibility-only switch; no current caller sets
            this True. Faithful engine runs must leave this False.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
        db_path: Optional override for the SQLite database path.

    Returns:
        A :class:`GroundingResult` with the blocked ids and per-id reasons.
    """
    target = GroundingTarget(
        allow_speculative=allow_speculative, conn=conn, db_path=db_path
    )
    blocked: set[str] = set()
    unverified = 0
    reason_by_id: dict[str, str] = {}
    for hyp_id, assessments in assessed:
        gate = _ground_one_hypothesis(run_id, hyp_id, assessments, target)
        reason_by_id[hyp_id] = gate.reason
        if gate.decision is GateDecision.BLOCK:
            blocked.add(hyp_id)
            if not _has_supported_claim(assessments):
                unverified += 1
    _log_gate_outcome(len(blocked), unverified, len(reason_by_id))
    return GroundingResult(
        blocked_ids=frozenset(blocked), reason_by_id=reason_by_id
    )


def _has_supported_claim(
    assessments: Sequence[tuple[ClaimAssessment, str]],
) -> bool:
    """Whether any claim has a ``supports`` or ``partial`` verdict.

    The same rule the report's "Verified" count and "Unverified" badge use
    (``report_content_gates._supported_hypothesis_ids``). The gate itself is
    stricter -- it also fails a hypothesis that has support for some claims
    but not for a categorical one -- so a gate failure alone does not mean
    the idea is published unverified.
    """
    return any(
        assessment.label in _SUPPORTING_LABELS
        for assessment, _role in assessments
    )


def _log_gate_outcome(
    blocked_count: int, unverified_count: int, gated_count: int
) -> None:
    """Log the claim gate's tally for a pass, warning only when it took all.

    A pass that fails some hypotheses is the gate discriminating; a pass that
    fails every one of them says more about the evidence the pool was assessed
    against than about any single hypothesis, and is the state worth
    surfacing -- it means the run published nothing an evidence passage
    actually supports.

    Both lines describe the report, not a withholding: failing this gate does
    not remove an idea from the report (see ``_record_blocked_hypothesis``).
    Only an idea with no supported claim at all is badged "Unverified"; the
    line used to call every gate failure "published unverified", which
    contradicted the report's own verified count for the same run.
    """
    if not gated_count:
        return
    if unverified_count == gated_count:
        logger.warning(
            "No hypothesis cleared the claim gate: all %s published unverified",
            gated_count,
        )
        return
    logger.info(
        "Claim gate: %s of %s hypotheses failed "
        "(%s published unverified, the rest with unsupported claims flagged)",
        blocked_count,
        gated_count,
        unverified_count,
    )


def _ground_one_hypothesis(
    run_id: str,
    hyp_id: str,
    assessments: list[tuple[ClaimAssessment, str]],
    target: GroundingTarget,
) -> GateResult:
    """Persist one hypothesis's claim edges, gate it, and record the verdict.

    The gate's verdict is recorded, not enforced here. Contradicted ideas are
    withheld from the report by the contradiction gate; ideas that merely lack
    support are ranked and published under an "Unverified" badge, which is the
    rank-and-publish policy the report layer implements. Treating a missing
    supporting passage as grounds for withholding would suppress most of a
    run: evidence retrieval finds direct support for a minority of claims.
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
        # Info, not warning: see _record_blocked_hypothesis.
        logger.info(
            "Hypothesis %s did not clear the claim gate (%s): %s",
            hyp_id,
            _publication_outcome(gate, assessments),
            gate.reason,
        )
    return gate


def _publication_outcome(
    gate: GateResult, assessments: Sequence[tuple[ClaimAssessment, str]]
) -> str:
    """Say what the report does with a hypothesis that failed the gate."""
    if gate.failed_claims and set(gate.failed_claims) <= set(
        gate.contradicted_claims
    ):
        return "withheld from the report"
    if _has_supported_claim(assessments):
        return "published with unsupported claims flagged"
    return "published unverified"


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
                verification_method=assessment.verification_method,
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
    """Persist the block decision for a hypothesis that failed the gate.

    The recorded matches come from ``gate.failed_claims``: the gate already
    knows which of its rules fired and which claims that rule was about, so
    re-deriving the set out here could only ever approximate it.
    """
    store.add_safety_decision(
        store.NewSafetyDecision(
            run_id=run_id,
            stage="claim_gate",
            decision="block",
            reason=f"hypothesis {hyp_id}: {gate.reason}",
            matches=list(gate.failed_claims),
        ),
        db_path=db_path,
        conn=conn,
    )
    # The quarantine line (logged by the caller) says what actually happens.
    # Under the rank-and-publish policy (see
    # report_content_gates.unverified_hypothesis_ids) failing this gate does
    # not withhold an idea: only a *contradicted* claim does that. An
    # unsupported one is published, and it carries the "Unverified" badge only
    # when it has no supported claim at all. This line used to announce a
    # quarantine "from ranking and publication" that nothing performs, and
    # then "published unverified" for ideas the report counted as verified.
    #
    # Info, not warning, for the same reason as the redaction line: one row
    # per assessed hypothesis is a per-item verdict, already persisted as the
    # claim_gate safety_decision above and counted in the run's
    # citation.grounding event.
