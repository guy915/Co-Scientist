"""Claim-level grounding wiring for the pipeline (Milestone 5 / M9)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import sqlite3
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import app.store as store
from app.claims import (
    _ASSESSOR_DETERMINISTIC,
    Assessor,
    BatchAssessor,
    EvidencePassage,
    GateDecision,
    GateResult,
    assess_claim,
    assess_claims_batch,
    deterministic_assessor,
    extract_atomic_claims,
    publication_gate,
    retrieve_passages,
)
from app.claims.assessor import _DEFAULT_RETRIEVAL_TOP_K
from app.claims.gate import (
    ClaimAssessment,
    ClaimRole,
    EntailmentLabel,
    SupportSpan,
    is_speculative,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class ClaimRecord:
    """One atomic claim and the role it plays in its hypothesis."""

    claim: str
    role: str


def _passage_identity(passage: Any) -> dict[str, str]:
    """Return the fields of a passage that can move a verdict."""
    return {
        "evidence_id": str(passage.evidence_id),
        "text": str(passage.text),
        "source": str(passage.source),
        "url": str(passage.url),
    }


def claim_fingerprint(
    record: ClaimRecord,
    passages: Sequence[Any],
    assessor_id: str,
    top_k: int = _DEFAULT_RETRIEVAL_TOP_K,
) -> str:
    """Hash one claim and only the evidence that can reach its verdict.

    Runs the same retrieval ``assess_claim`` performs, so the digest covers
    exactly the assessor's input rather than an approximation of it.

    Args:
        record: The claim and the role it carries.
        passages: The run's full evidence pool, scoped per claim here.
        assessor_id: Provenance id of the assessor that would run.
        top_k: Retrieval budget, matching ``assess_claim``'s own.

    Returns:
        A hex digest identifying this claim's assessment inputs.
    """
    payload = {
        "assessor": assessor_id,
        "claim": record.claim,
        "role": record.role,
        "evidence": [
            _passage_identity(passage)
            for passage in retrieve_passages(
                record.claim, passages, top_k=top_k
            )
        ],
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def combined_fingerprint(claim_fingerprints: Sequence[str]) -> str:
    """Fold per-claim digests into one whole-hypothesis digest.

    Takes the digests rather than recomputing them: each one costs a
    retrieval pass over the whole pool, and the gate needs both levels for
    every claim it plans.
    """
    return hashlib.sha256(
        json.dumps(list(claim_fingerprints), separators=(",", ":")).encode()
    ).hexdigest()


def _span_from_dict(payload: Mapping[str, Any]) -> SupportSpan:
    """Rebuild one cited evidence span from its stored form."""
    return SupportSpan(
        evidence_id=str(payload.get("evidence_id") or ""),
        quote=str(payload.get("quote") or ""),
        start=int(payload.get("start") or 0),
        end=int(payload.get("end") or 0),
        source=str(payload.get("source") or ""),
        url=str(payload.get("url") or ""),
    )


def _spans_from(
    payload: Mapping[str, Any], key: str
) -> tuple[SupportSpan, ...]:
    """Rebuild one side's cited spans from a stored claim record."""
    return tuple(
        _span_from_dict(span)
        for span in payload.get(key) or ()
        if isinstance(span, Mapping)
    )


def _restore_one(
    record: Mapping[str, Any], assessor_id: str
) -> ClaimAssessment | None:
    """Rebuild one stored claim verdict, or None when it is unusable."""
    claim = str(record.get("claim") or "")
    label = str(record.get("label") or "")
    if not claim or label not in {item.value for item in EntailmentLabel}:
        return None
    return ClaimAssessment(
        claim=claim,
        label=EntailmentLabel(label),
        supporting_passages=_spans_from(record, "supporting_passages"),
        contradicting_passages=_spans_from(record, "contradicting_passages"),
        assessor=assessor_id,
        verification_method=str(
            record.get("verification_method") or "legacy_unknown"
        ),
    )


def reusable_assessments(
    gate_record: Mapping[str, Any] | None,
) -> dict[str, ClaimAssessment]:
    """Index a stored gate verdict's claims by their input fingerprint.

    A record missing its per-claim fingerprint is skipped rather than
    guessed at: it was written before fingerprints were stored, and reusing
    it would assert a verdict is current against inputs nobody recorded.

    Args:
        gate_record: The hypothesis's stored ``claim_gate`` enrichment.

    Returns:
        Fingerprint to assessment, for whatever is safely reusable.
    """
    if not gate_record:
        return {}
    assessor_id = str(gate_record.get("assessor") or "")
    reusable: dict[str, ClaimAssessment] = {}
    for record in gate_record.get("claims") or ():
        if not isinstance(record, Mapping):
            continue
        fingerprint = str(record.get("fingerprint") or "")
        restored = _restore_one(record, assessor_id) if fingerprint else None
        if restored is not None:
            reusable[fingerprint] = restored
    return reusable


# How many claims are assessed at once. Sized against the provider, which
# returns twenty-four concurrent completions in the same wall clock as four,
# and kept below that so several runs finalizing together still share it
# comfortably. Unlike the durable cohort this costs no database writes --
# assessment persists nothing -- so SQLite's single writer does not bound it.
# Shared with the pre-ranking evidence gate (``engine_tasks``), which assesses
# the same kind of claim against the same provider.
ASSESSMENT_CONCURRENCY = 12

# Hypothesis fields whose text is decomposed into atomic claims. The statement
# and expected effect are visibly proposed idea content; mechanism stores the
# literature-grounding rationale and must remain categorical/evidence-backed.
_CLAIM_FIELD_ROLES = (
    ("statement", ClaimRole.SPECULATIVE.value),
    ("mechanism", ClaimRole.CATEGORICAL.value),
    ("expected_effect", ClaimRole.SPECULATIVE.value),
)


@dataclasses.dataclass(frozen=True)
class AssessorSpec:
    """Which entailment assessor to run, and the provenance id it records.

    Attributes:
        assessor: The entailment assessor (deterministic by default).
        assessor_id: Provenance id recorded on each persisted edge.
        batch_assessor: The batch-capable assessor, if any -- when set,
            each hypothesis's claims are judged in one call rather than
            one call per claim (see ``app.claims.assess_claims_batch``).
    """

    assessor: Assessor = deterministic_assessor
    assessor_id: str = _ASSESSOR_DETERMINISTIC
    batch_assessor: BatchAssessor | None = None


def _claim_records(hyp: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return atomic claims paired with their categorical/speculative role."""
    roles: dict[str, str] = {}
    ordered: list[str] = []
    for field, role in _CLAIM_FIELD_ROLES:
        for claim in extract_atomic_claims(str(hyp.get(field) or "")):
            if claim not in roles:
                ordered.append(claim)
                roles[claim] = role
            elif role == ClaimRole.CATEGORICAL:
                # The strict role wins when identical text appears in both
                # rationale and proposed-idea fields.
                roles[claim] = role
    return [(claim, roles[claim]) for claim in ordered]


def assess_claim_groups(
    groups: Sequence[Sequence[str]],
    passages: Sequence[EvidencePassage],
    spec: AssessorSpec,
    *,
    parallel: bool = True,
) -> list[list[ClaimAssessment]]:
    """Assess independent groups of claims in one bounded wave.

    The one wave policy shared by both claim-assessment paths (the drain's
    grounding pass and the pre-ranking evidence gate), so pool sizing and
    ordering guarantees cannot drift between them. Claims are independent, so
    overlapping them changes no verdict, only how long the phase takes; the
    provider is not the constraint (twenty-four concurrent completions
    return in the same wall clock as four).

    When ``spec.batch_assessor`` is given, each group (a hypothesis's
    claims) is judged in one call instead of one call per claim -- see
    ``app.claims.assess_claims_batch``. ``spec.assessor`` governs the flat,
    per-claim path used whenever ``spec.batch_assessor`` is None (the
    deterministic assessor has no call to batch).

    Args:
        groups: Per group (typically one hypothesis), its claims in order.
        passages: Candidate evidence passages each claim is assessed against.
        spec: Which assessor to run (and its batch-capable counterpart, if
            any) plus the provenance id recorded on each assessment.
        parallel: When False, assess serially (no provider call to gain).

    Returns:
        Per group, its claim assessments, preserving the group's own order.
    """
    if not groups:
        return []
    if spec.batch_assessor is not None:
        return _assess_grouped_batches(
            groups,
            passages,
            batch_assessor=spec.batch_assessor,
            assessor_id=spec.assessor_id,
            parallel=parallel,
        )
    flat = [
        (index, claim) for index, group in enumerate(groups) for claim in group
    ]
    if not flat:
        return [[] for _ in groups]
    results = _assess_flat_claims(
        flat,
        passages,
        assessor=spec.assessor,
        assessor_id=spec.assessor_id,
        parallel=parallel,
    )
    return _regroup_assessments(groups, flat, results)


def _assess_grouped_batches(
    groups: Sequence[Sequence[str]],
    passages: Sequence[EvidencePassage],
    *,
    batch_assessor: BatchAssessor,
    assessor_id: str,
    parallel: bool,
) -> list[list[ClaimAssessment]]:
    """Assess each group in its own single (or split) batched call.

    Shares ``ASSESSMENT_CONCURRENCY`` with the flat per-claim path so the
    two callers cannot drift on how many provider calls run at once; here
    each unit of work is one hypothesis's whole claim set rather than one
    claim.
    """

    def _assess_one(group: Sequence[str]) -> list[ClaimAssessment]:
        return assess_claims_batch(
            group,
            passages,
            batch_assessor=batch_assessor,
            assessor_id=assessor_id,
        )

    if parallel and len(groups) > 1:
        from app.async_bridge import propagate_context

        with ThreadPoolExecutor(
            max_workers=min(ASSESSMENT_CONCURRENCY, len(groups))
        ) as pool:
            return list(pool.map(propagate_context(_assess_one), groups))
    return [_assess_one(group) for group in groups]


def _regroup_assessments(
    groups: Sequence[Sequence[str]],
    flat: list[tuple[int, str]],
    results: list[ClaimAssessment],
) -> list[list[ClaimAssessment]]:
    """Scatter flat assessment results back into their group's own list."""
    grouped: list[list[ClaimAssessment]] = [[] for _ in groups]
    for (index, _claim), assessment in zip(flat, results, strict=True):
        grouped[index].append(assessment)
    return grouped


def _assess_flat_claims(
    flat: list[tuple[int, str]],
    passages: Sequence[EvidencePassage],
    *,
    assessor: Assessor,
    assessor_id: str,
    parallel: bool,
) -> list[ClaimAssessment]:
    """Assess a flattened (group_index, claim) list, preserving input order."""

    def _assess_one(item: tuple[int, str]) -> ClaimAssessment:
        return assess_claim(
            item[1], passages, assessor=assessor, assessor_id=assessor_id
        )

    if parallel:
        from app.async_bridge import propagate_context

        # ``ThreadPoolExecutor`` does not copy this thread's contextvars
        # into its workers -- the caller's run-scoped LLM-call budget and
        # telemetry phase (see engine_tasks.gate/drain) would otherwise
        # silently vanish for every claim an LLM assessor assesses here.
        # ``map`` preserves input order.
        with ThreadPoolExecutor(
            max_workers=min(ASSESSMENT_CONCURRENCY, len(flat))
        ) as pool:
            return list(pool.map(propagate_context(_assess_one), flat))
    return [_assess_one(item) for item in flat]


def assess_hypothesis_claims(
    hyps: Sequence[Mapping[str, Any]],
    passages: Sequence[EvidencePassage],
    spec: AssessorSpec | None = None,
    *,
    reuse: Mapping[str, Mapping[str, ClaimAssessment]] | None = None,
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
        spec: Which assessor to run (deterministic when omitted) plus its
            provenance id and, when set, a batch-capable counterpart that
            judges each hypothesis's still-pending claims in one call
            instead of one call per claim (see
            ``app.claims.assess_claims_batch``).
        reuse: Per hypothesis id, verdicts already produced for these same
            inputs, keyed by claim fingerprint. Matching claims skip the
            assessor; everything else is assessed as usual.

    Returns:
        Per hypothesis id, its ``(assessment, role)`` pairs, in input order.
    """
    spec = spec or AssessorSpec()
    candidates = [p for p in passages if p.text]
    per_hypothesis = _per_hypothesis_claim_records(hyps)
    plans = [
        _plan_claim_group(
            hyp_id, records, candidates, spec.assessor_id, reuse or {}
        )
        for hyp_id, records in per_hypothesis
    ]
    grouped = assess_claim_groups(
        [plan.to_assess for plan in plans], candidates, spec
    )
    return [
        (plan.hypothesis_id, plan.merge(assessed))
        for plan, assessed in zip(plans, grouped, strict=True)
    ]


@dataclasses.dataclass(frozen=True)
class _ClaimGroupPlan:
    """One hypothesis's claims, split into reused verdicts and pending work.

    Attributes:
        hypothesis_id: The hypothesis these claims belong to.
        records: Its claims and roles, in the order results must come back.
        reused: Verdicts carried over, keyed by claim text.
        to_assess: The claims that still need the assessor, in order.
    """

    hypothesis_id: str
    records: list[tuple[str, str]]
    reused: dict[str, ClaimAssessment]
    to_assess: list[str]

    def merge(
        self, assessed: Sequence[ClaimAssessment]
    ) -> list[tuple[ClaimAssessment, str]]:
        """Interleave freshly assessed claims back into the original order.

        Order is the caller's contract -- persistence and the publication
        gate both walk these positionally -- so reuse must not reorder a
        hypothesis's claims.
        """
        pending = iter(assessed)
        return [
            (self.reused.get(claim) or next(pending), role)
            for claim, role in self.records
        ]


def _plan_claim_group(
    hypothesis_id: str,
    records: list[tuple[str, str]],
    candidates: Sequence[EvidencePassage],
    assessor_id: str,
    reuse: Mapping[str, Mapping[str, ClaimAssessment]],
) -> _ClaimGroupPlan:
    """Split one hypothesis's claims into reusable verdicts and pending work."""
    pass

    available = reuse.get(hypothesis_id) or {}
    reused: dict[str, ClaimAssessment] = {}
    if available:
        for claim, role in records:
            fingerprint = claim_fingerprint(
                ClaimRecord(claim, role), candidates, assessor_id
            )
            match = available.get(fingerprint)
            if match is not None:
                reused[claim] = match
    return _ClaimGroupPlan(
        hypothesis_id=hypothesis_id,
        records=records,
        reused=reused,
        to_assess=[claim for claim, _role in records if claim not in reused],
    )


def _per_hypothesis_claim_records(
    hyps: Sequence[Mapping[str, Any]],
) -> list[tuple[str, list[tuple[str, str]]]]:
    """Return each hypothesis id paired with its (claim, role) records."""
    return [
        (hyp_id, _claim_records(hyp))
        for hyp in hyps
        if (hyp_id := str(hyp.get("id") or ""))
    ]


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
    from app.engine_adapter import offline_mode

    if mode == "llm" and not offline_mode():
        from app.claims.verifier import make_llm_assessor

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
    from app.engine_adapter import offline_mode

    if mode == "llm" and not offline_mode():
        from app.claims.verifier import make_llm_batch_assessor

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
    # report.gates.exclude_unsafe_hypotheses) and publishes merely
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
    (``claims.verdict.is_supporting``). The gate itself is
    stricter -- it also fails a hypothesis that has support for some claims
    but not for a categorical one -- so a gate failure alone does not mean
    the idea is published unverified.
    """
    return any(
        assessment.label.is_supporting for assessment, _role in assessments
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
            if is_speculative(role)
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
    # report.gates.unverified_hypothesis_ids) failing this gate does
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


__all__ = ["AssessorSpec", "assess_claim_groups", "assess_hypothesis_claims"]
