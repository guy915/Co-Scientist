"""The provider half of claim grounding: assessment, never persistence.

Split out of :mod:`app.claim_grounding`, which had grown past the
module-size budget. Everything here is deliberately database-free. The
assessor may be an LLM, and one synchronous call per claim used to run
inside the drain's single write transaction -- so the process held
SQLite's one write lock across minutes of provider I/O and every other
writer starved. Keeping the assessment half in its own module makes that
boundary a physical one: nothing in this file may open a connection, and
``claim_grounding.persist_grounding`` is what callers run afterwards.

:mod:`app.claim_grounding` imports these names back and re-exports them,
so every name remains importable (and monkeypatchable) from
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
    Assessor,
    ClaimAssessment,
    EvidencePassage,
    assess_claim,
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
    """

    assessor: Assessor = deterministic_assessor
    assessor_id: str = "deterministic-v1"


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
    *,
    assessor: Assessor,
    assessor_id: str,
    parallel: bool = True,
) -> list[list[ClaimAssessment]]:
    """Assess independent groups of claims in one bounded wave.

    The one wave policy shared by both claim-assessment paths (the drain's
    grounding pass and the pre-ranking evidence gate), so pool sizing and
    ordering guarantees cannot drift between them. Claims are independent, so
    overlapping them changes no verdict, only how long the phase takes; the
    provider is not the constraint (twenty-four concurrent completions
    return in the same wall clock as four).

    Args:
        groups: Per group (typically one hypothesis), its claims in order.
        passages: Candidate evidence passages each claim is assessed against.
        assessor: The entailment assessor.
        assessor_id: Provenance id recorded on each assessment.
        parallel: When False, assess serially (no provider call to gain).

    Returns:
        Per group, its claim assessments, preserving the group's own order.
    """
    flat = [
        (index, claim) for index, group in enumerate(groups) for claim in group
    ]
    if not flat:
        return [[] for _ in groups]
    results = _assess_flat_claims(
        flat,
        passages,
        assessor=assessor,
        assessor_id=assessor_id,
        parallel=parallel,
    )
    return _regroup_assessments(groups, flat, results)


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
        # ``map`` preserves input order.
        with ThreadPoolExecutor(
            max_workers=min(ASSESSMENT_CONCURRENCY, len(flat))
        ) as pool:
            return list(pool.map(_assess_one, flat))
    return [_assess_one(item) for item in flat]


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
    per_hypothesis = _per_hypothesis_claim_records(hyps)
    grouped = assess_claim_groups(
        [
            [claim for claim, _role in records]
            for _id, records in per_hypothesis
        ],
        candidates,
        assessor=assessor,
        assessor_id=assessor_id,
    )
    return _zip_hypothesis_assessments(per_hypothesis, grouped)


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
