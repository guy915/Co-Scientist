"""The scope probe must not accept wrong labels or invented support quotes."""

import pytest
from app.claims import AssessorDraft, EntailmentLabel

from scope_controls import evaluate_scope_controls

DATASET = {
    "items": [
        {
            "id": "same_context_partial",
            "claim": "Treatment reduces cell growth and migration.",
            "passages": ["Treatment reduces cell growth; migration was not measured."],
            "allowed_labels": ["partial"],
        }
    ]
}


def judge(claim, passages):
    return AssessorDraft(
        EntailmentLabel.PARTIAL,
        supporting=((passages[0].evidence_id, passages[0].text),),
        verification_method="model_primary",
    )


def test_single_control_retains_located_quote():
    result = evaluate_scope_controls(DATASET, judge, "test")
    assert result["passed"]
    assert result["checks"][0]["label"] == "partial"
    assert (
        result["checks"][0]["quotes"][0]["quote"] == DATASET["items"][0]["passages"][0]
    )


def test_fabricated_quote_cannot_satisfy_the_control():
    def fabricated(claim, passages):
        return AssessorDraft(
            EntailmentLabel.PARTIAL,
            supporting=((passages[0].evidence_id, "not present"),),
        )

    assert not evaluate_scope_controls(DATASET, fabricated, "test")["passed"]


def test_wrong_label_does_not_pass_merely_by_locating_a_quote():
    def wrong(claim, passages):
        return AssessorDraft(
            EntailmentLabel.SUPPORTS,
            supporting=((passages[0].evidence_id, passages[0].text),),
        )

    assert not evaluate_scope_controls(DATASET, wrong, "test")["passed"]


def test_batch_interface_is_exercised_with_each_controls_own_evidence():
    calls = []

    def batch(claims, passages):
        calls.append((list(claims), list(passages)))
        return [judge(claims[0], passages)]

    result = evaluate_scope_controls(DATASET, batch, "test", batch=True)
    assert result["passed"]
    assert result["mode"] == "batch_single_claim"
    assert len(calls) == 1
    assert calls[0][0] == [DATASET["items"][0]["claim"]]


def test_empty_controls_cannot_vacuously_pass():
    with pytest.raises(ValueError, match="empty"):
        evaluate_scope_controls({"items": []}, judge, "test")


def test_no_retrieval_cannot_pass_an_insufficient_control_without_a_judgment():
    dataset = {
        "items": [
            {
                "id": "no_candidate",
                "claim": "Mitochondria control metabolism.",
                "passages": ["Volcanoes erupt."],
                "allowed_labels": ["insufficient"],
            }
        ]
    }

    def unused(claim, passages):
        assert not passages
        return AssessorDraft(EntailmentLabel.INSUFFICIENT)

    result = evaluate_scope_controls(dataset, unused, "test")
    assert not result["passed"]
    assert result["checks"][0]["nonempty_assessor_invocations"] == 0


def test_recorded_fallback_cannot_pass_a_model_control():
    def fallback(claim, passages):
        return AssessorDraft(
            EntailmentLabel.PARTIAL,
            supporting=((passages[0].evidence_id, passages[0].text),),
            verification_method="deterministic_lexical",
        )

    assert not evaluate_scope_controls(DATASET, fallback, "test")["passed"]


@pytest.mark.parametrize("method", ["legacy_unknown", "no_evidence", "unrecognized"])
def test_unproven_provenance_cannot_pass(method):
    def unproven(claim, passages):
        return AssessorDraft(
            EntailmentLabel.PARTIAL,
            supporting=((passages[0].evidence_id, passages[0].text),),
            verification_method=method,
        )

    assert not evaluate_scope_controls(DATASET, unproven, "test")["passed"]


def test_model_scope_panels_use_both_factories_and_completed_capture(monkeypatch):
    from contextlib import contextmanager
    from app import claim_verifier, claim_verifier_batch
    from evaluations import _panel_identity
    from scope_controls import evaluate_model_scope_controls

    factories = []

    def single(model):
        factories.append(("single", model))
        return judge, "test-single"

    def batch(model):
        factories.append(("batch", model))
        return lambda claims, passages: [judge(claims[0], passages)], "test-batch"

    @contextmanager
    def capture(panel, dataset, model, *, live):
        assert panel == "citation_entailment"
        assert dataset == DATASET
        assert live
        evidence = {"model": model}
        yield evidence
        evidence["capture_completed"] = True

    monkeypatch.setattr(claim_verifier, "make_llm_assessor", single)
    monkeypatch.setattr(claim_verifier_batch, "make_llm_batch_assessor", batch)
    monkeypatch.setattr(_panel_identity, "capture_panel", capture)
    results = evaluate_model_scope_controls(DATASET, "test-model")
    assert factories == [("single", "test-model"), ("batch", "test-model")]
    assert set(results) == {"single", "batch_single_claim"}
    assert all(r["passed"] and r["capture_completed"] for r in results.values())


def test_scope_evidence_requires_each_mode_and_physical_calls():
    from scope_controls import validate_scope_evidence

    with pytest.raises(ValueError, match="modes"):
        validate_scope_evidence({"scope_controls": {}}, DATASET)


@pytest.mark.parametrize(
    "missing", ["physical_calls", "observed_models", "unreported_usage_calls"]
)
def test_scope_evidence_rejects_missing_telemetry(missing):
    from scope_controls import validate_scope_evidence

    record = scope_record()
    del record["scope_controls"]["single"]["usage_evidence"][missing]
    with pytest.raises((ValueError, KeyError)):
        validate_scope_evidence(record, DATASET)


def scope_record():
    result = evaluate_scope_controls(DATASET, judge, "test")
    usage = {
        "physical_calls": 1,
        "observed_models": ["openrouter/test-model"],
        "unobserved_model_calls": 0,
        "unreported_usage_calls": 0,
        "recorded_deterministic_fallbacks": {},
    }
    from copy import deepcopy

    return {
        "requested_model": "openrouter/test-model",
        "scope_controls": {
            mode: {**deepcopy(result), "mode": mode, "usage_evidence": deepcopy(usage)}
            for mode in ("single", "batch_single_claim")
        },
        "physical_requests": [
            {"phase": "scope_" + mode} for mode in ("single", "batch_single_claim")
        ],
    }


def test_scope_evidence_validates_all_ids_and_candidate_checks():
    from scope_controls import validate_scope_evidence

    record = scope_record()
    assert validate_scope_evidence(record, DATASET)
    record["scope_controls"]["batch_single_claim"]["checks"][0]["passed"] = False
    assert not validate_scope_evidence(record, DATASET)
    record["scope_controls"]["batch_single_claim"]["checks"] = []
    with pytest.raises(ValueError, match="items"):
        validate_scope_evidence(record, DATASET)
