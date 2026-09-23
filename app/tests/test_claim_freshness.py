"""Reusing claim verdicts whose assessment inputs have not moved.

The pre-ranking gate and the final drain assess the same hypotheses. These
tests pin what makes carrying a verdict across safe: a claim's verdict
depends only on itself and the passages it retrieves, so evidence that
never reaches it cannot make it stale, and a claim whose own evidence
moved must be re-assessed.
"""

from __future__ import annotations

from typing import Any

from app.claim_freshness import (
    ClaimRecord,
    claim_fingerprint,
    reusable_assessments,
)
from app.claim_grounding_assess import AssessorSpec, assess_hypothesis_claims
from app.claims import AssessorDraft, EntailmentLabel, as_passages

_CLAIM = "Inhibiting kinase X reduces melanoma tumor growth in mouse models."
_OTHER = "A dietary change improves cardiovascular outcomes in adults."

_RELEVANT = (
    "In mouse models, inhibiting kinase X reduced melanoma tumor growth "
    "substantially across every cohort."
)
_UNRELATED = (
    "Sediment cores from the Baltic show a shift in diatom assemblages "
    "during the mid-Holocene."
)


def _passages(*texts: str) -> Any:
    """Build evidence passages from raw text, one per supplied string."""
    return as_passages(list(texts))


def _hypothesis(hyp_id: str = "h1") -> dict[str, Any]:
    """A persisted-row-shaped hypothesis carrying one claim per field."""
    return {"id": hyp_id, "statement": _CLAIM, "mechanism": _OTHER}


def _counting_assessor() -> tuple[Any, list[str]]:
    """An assessor that records every claim it is asked to judge."""
    seen: list[str] = []

    def _assessor(claim: str, _passages: Any) -> AssessorDraft:
        seen.append(claim)
        return AssessorDraft(
            label=EntailmentLabel.INSUFFICIENT,
            supporting=(),
            contradicting=(),
        )

    return _assessor, seen


def _gate_record(
    claims: list[tuple[str, str, str]], assessor_id: str = "test-v1"
) -> dict[str, Any]:
    """A stored gate verdict over (claim, role, fingerprint) triples."""
    return {
        "assessor": assessor_id,
        "claims": [
            {
                "claim": claim,
                "role": role,
                "fingerprint": fingerprint,
                "label": EntailmentLabel.SUPPORTS.value,
                "supporting_passages": [],
                "contradicting_passages": [],
            }
            for claim, role, fingerprint in claims
        ],
    }


def test_unrelated_evidence_does_not_change_a_claim_fingerprint() -> None:
    """Evidence a claim never retrieves cannot make its verdict stale.

    The assessor is only ever shown the claim's top-k passages, so
    fingerprinting the whole pool would invalidate every stored verdict
    whenever any article arrived -- and the drain runs after a run has
    finished retrieving, so it would reuse nothing.
    """
    record = ClaimRecord(_CLAIM, "speculative")

    before = claim_fingerprint(record, _passages(_RELEVANT), "test-v1")
    after = claim_fingerprint(
        record, _passages(_RELEVANT, _UNRELATED), "test-v1"
    )

    assert before == after


def test_changed_relevant_evidence_changes_the_fingerprint() -> None:
    """Evidence the claim does retrieve is a new input to its verdict."""
    record = ClaimRecord(_CLAIM, "speculative")

    before = claim_fingerprint(record, _passages(_RELEVANT), "test-v1")
    after = claim_fingerprint(record, _passages(), "test-v1")

    assert before != after


def test_a_different_assessor_invalidates_a_stored_verdict() -> None:
    """A verdict from another assessor is not carried over as current."""
    record = ClaimRecord(_CLAIM, "speculative")
    passages = _passages(_RELEVANT)

    assert claim_fingerprint(record, passages, "test-v1") != (
        claim_fingerprint(record, passages, "other-v2")
    )


def test_matching_claims_skip_the_assessor() -> None:
    """A claim the gate already judged on these inputs is not re-judged."""
    passages = _passages(_RELEVANT)
    assessor, seen = _counting_assessor()
    fingerprint = claim_fingerprint(
        ClaimRecord(_CLAIM, "speculative"), passages, "test-v1"
    )

    result = assess_hypothesis_claims(
        [_hypothesis()],
        passages,
        AssessorSpec(assessor, "test-v1"),
        reuse={
            "h1": reusable_assessments(
                _gate_record([(_CLAIM, "speculative", fingerprint)])
            )
        },
    )

    # The statement's claim was reused; the mechanism's was not stored.
    assert _CLAIM not in seen
    assert _OTHER in seen
    claims = [assessment.claim for assessment, _role in result[0][1]]
    assert claims == [_CLAIM, _OTHER]


def test_reuse_preserves_claim_order_and_roles() -> None:
    """Persistence walks these positionally, so reuse must not reorder."""
    passages = _passages(_RELEVANT)
    assessor, _seen = _counting_assessor()
    fingerprint = claim_fingerprint(
        ClaimRecord(_OTHER, "categorical"), passages, "test-v1"
    )

    result = assess_hypothesis_claims(
        [_hypothesis()],
        passages,
        AssessorSpec(assessor, "test-v1"),
        reuse={
            "h1": reusable_assessments(
                _gate_record([(_OTHER, "categorical", fingerprint)])
            )
        },
    )

    pairs = [(a.claim, role) for a, role in result[0][1]]
    assert pairs == [(_CLAIM, "speculative"), (_OTHER, "categorical")]
    # The reused verdict kept the label the gate recorded, not a fresh one.
    assert result[0][1][1][0].label is EntailmentLabel.SUPPORTS


def test_a_record_without_a_fingerprint_is_never_reused() -> None:
    """A verdict predating fingerprints has no recorded inputs to trust."""
    record = _gate_record([(_CLAIM, "speculative", "")])

    assert reusable_assessments(record) == {}


def test_no_gate_record_assesses_everything() -> None:
    """Absent history, every claim goes to the assessor as before."""
    passages = _passages(_RELEVANT)
    assessor, seen = _counting_assessor()

    assess_hypothesis_claims(
        [_hypothesis()],
        passages,
        AssessorSpec(assessor, "test-v1"),
        reuse={},
    )

    assert sorted(seen) == sorted([_CLAIM, _OTHER])


def test_gate_telemetry_is_folded_into_the_run_metrics() -> None:
    """Grounding's provider calls must count against a run's telemetry.

    Entailment calls route through the engine's ``call_llm_json`` seam
    (``app.claim_verifier``), so ``scoped_telemetry`` already captures
    their tokens/cost/call count per (phase, model); this only has to fold
    that snapshot into the run's live metrics, the same reducer every
    engine node commit uses.
    """
    from co_scientist.models import ExecutionMetrics

    from app import engine_tasks_gate

    state: dict[str, Any] = {"metrics": ExecutionMetrics(llm_calls=7)}
    usage = {"claim_gate::llm:test-model": {"calls": 25, "prompt_tokens": 100}}

    engine_tasks_gate._fold_gate_telemetry(state, usage)

    entry = state["metrics"].model_usage["claim_gate::llm:test-model"]
    assert entry["calls"] == 25
    assert entry["prompt_tokens"] == 100
    assert state["metrics"].llm_calls == 32


def test_a_gate_pass_that_made_no_calls_charges_nothing() -> None:
    """A fully-reused gate pass must not manufacture a metrics key."""
    from co_scientist.models import ExecutionMetrics

    from app import engine_tasks_gate

    state: dict[str, Any] = {"metrics": ExecutionMetrics(llm_calls=7)}

    engine_tasks_gate._fold_gate_telemetry(state, {})

    assert state["metrics"].llm_calls == 7
    assert state["metrics"].model_usage == {}


def test_reused_assessment_preserves_verification_method() -> None:
    record = _gate_record([(_CLAIM, "speculative", "fixed-fingerprint")])
    record["claims"][0]["verification_method"] = "model_opposition_verified"
    restored = reusable_assessments(record)
    assert (
        restored["fixed-fingerprint"].verification_method
        == "model_opposition_verified"
    )


def test_legacy_reused_assessment_has_unknown_method() -> None:
    record = _gate_record([(_CLAIM, "speculative", "fixed-fingerprint")])
    assert (
        reusable_assessments(record)["fixed-fingerprint"].verification_method
        == "legacy_unknown"
    )
