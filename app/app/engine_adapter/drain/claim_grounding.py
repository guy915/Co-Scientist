"""Claim-grounding assessment for the final-state drain: provider work only.

The drain's provider-only phase for claim grounding, alongside its sibling
``drain.escalation`` (the other one). Must run strictly between the drain's
two write transactions -- never inside either, since ``store.transaction``
takes SQLite's write lock the instant it opens and this must never hold that
lock across network I/O -- and must run off the caller's event loop, not
directly on it: a durable finalize task's lease heartbeat renews on that
same loop, and a synchronous wave here starves it for the wave's whole
duration (run b82f9162, 2026-09-06; see the root AGENTS.md lease/heartbeat
Gotcha).
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from typing import Any

from app.claims import EvidencePassage
from app.claims.grounding import (
    AssessorSpec,
    assess_hypothesis_claims,
    build_assessor,
    build_batch_assessor,
)
from app.config import settings
from app.engine_adapter.drain.inputs import FinalStateInputs
from app.execution_policy import effective_execution_model


async def _assess_claims(
    grounding_candidates: list[dict[str, Any]],
    passages: list[EvidencePassage],
    gate_records: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[Any, dict[str, dict[str, Any]]]:
    """Assess each hypothesis claim against retrieved evidence passages.

    Claims the pre-ranking gate already assessed against the same evidence
    are reused rather than re-derived. The gate assesses a strict superset
    of these claims (it reads the hypothesis's experiment field too) with
    the same roles on the overlap, and a claim's verdict depends only on
    itself and the passages it retrieves -- so a per-claim match is enough
    to carry the verdict across.

    The wave itself runs off this coroutine's event loop
    (``async_bridge.run_off_loop``), the same way the pre-ranking gate
    (``engine_tasks.gate._assess_gate_claims``) runs its own wave -- see
    the module docstring. ``scoped_telemetry("claim_grounding")``
    attributes this pass's LLM calls in the run's metrics separately from
    the pre-ranking gate's own ``"claim_gate"`` phase.

    Args:
        grounding_candidates: Persisted hypotheses not already rejected.
        passages: The run's evidence passages.
        gate_records: Per store-id, the hypothesis's stored ``claim_gate``
            enrichment; omitted means assess everything.

    Returns:
        A tuple of (per hypothesis id its ``(assessment, role)`` pairs in
        claim order, this pass's LLM telemetry snapshot).
    """
    from co_scientist.llm import scoped_telemetry

    from app.async_bridge import run_off_loop

    model = effective_execution_model(
        settings.claim_verifier_model or settings.model_name
    )
    assert model is not None
    assessor, assessor_id = build_assessor(settings.claim_assessor, model)
    batch_assessor = build_batch_assessor(settings.claim_assessor, model)
    spec = AssessorSpec(assessor, assessor_id, batch_assessor)
    call = functools.partial(
        assess_hypothesis_claims,
        grounding_candidates,
        passages,
        spec,
        reuse=_reusable_by_hypothesis(gate_records or {}),
    )
    with scoped_telemetry("claim_grounding") as telemetry:
        assessed = await run_off_loop(call)
    return assessed, telemetry.snapshot()


def _gate_records_by_store_id(
    inputs: FinalStateInputs,
    store_id_by_engine_id: Mapping[str, str],
) -> dict[str, Mapping[str, Any]]:
    """Map each persisted hypothesis to the gate verdict recorded for it.

    The gate's verdicts live on the engine hypothesis's enrichments, but
    the drain assesses the persisted rows, so the two have to be joined by
    the engine-to-store id map the persistence pass just built.
    """
    records: dict[str, Mapping[str, Any]] = {}
    for hypothesis in inputs.hyps_parents_first:
        engine_id = str(hypothesis.get("id") or "")
        store_id = store_id_by_engine_id.get(engine_id)
        gate = (hypothesis.get("enrichments") or {}).get("claim_gate")
        if store_id and isinstance(gate, Mapping):
            records[store_id] = gate
    return records


def _reusable_by_hypothesis(
    gate_records: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index every hypothesis's reusable gate verdicts by fingerprint."""
    from app.claims.freshness import reusable_assessments

    indexed = {
        store_id: reusable_assessments(record)
        for store_id, record in gate_records.items()
    }
    return {key: value for key, value in indexed.items() if value}
