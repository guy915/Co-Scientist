"""The provider half of claim grounding: assessment, never persistence.

Split out of :mod:`app.claim_grounding`, which had grown past the
module-size budget. Everything here is deliberately database-free. The
assessor may be an LLM, and one synchronous call per claim used to run
inside the drain's single write transaction -- so the process held
SQLite's one write lock across minutes of provider I/O and every other
writer starved. Keeping the assessment half in its own module makes that
boundary a physical one: nothing in this file may open a connection, and
``claim_grounding.persist_grounding`` is what callers run afterwards.

:mod:`app.claim_grounding` imports these names back and re-exports the ones
callers use, so they remain importable (and monkeypatchable) from
``app.claim_grounding`` exactly as before. This module deliberately does
**not** import :mod:`app.claim_grounding` -- that would create an import
cycle, since the grounding wiring depends on the names defined here.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.claims import (
    _ASSESSOR_DETERMINISTIC,
    Assessor,
    BatchAssessor,
    ClaimAssessment,
    EvidencePassage,
    assess_claim,
    assess_claims_batch,
    deterministic_assessor,
    extract_atomic_claims,
)

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
    ("statement", "speculative"),
    ("mechanism", "categorical"),
    ("expected_effect", "speculative"),
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
            elif role == "categorical":
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
        # telemetry phase (see engine_tasks_gate/drain) would otherwise
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
    from app.claim_freshness import ClaimRecord, claim_fingerprint

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


def _zip_hypothesis_assessments(
    per_hypothesis: list[tuple[str, list[tuple[str, str]]]],
    grouped: list[list[ClaimAssessment]],
) -> list[tuple[str, list[tuple[ClaimAssessment, str]]]]:
    """Pair each hypothesis's grouped assessments back with their claim role."""
    return [
        (
            hyp_id,
            [
                (assessment, role)
                for assessment, (_claim, role) in zip(
                    assessments, records, strict=True
                )
            ],
        )
        for (hyp_id, records), assessments in zip(
            per_hypothesis, grouped, strict=True
        )
    ]
