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
