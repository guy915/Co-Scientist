from typing import Any

import pytest

from evaluations.decision_relevance_fusion import validate_report


def _row(
    identifier: str, reference: dict[str, float], decision: dict[str, float]
) -> dict[str, Any]:
    return {
        "id": identifier,
        "reference": reference,
        "decision": decision,
        "confidence": 0.99,
        "answers": {name: {"confidence": 0.99} for name in decision},
        "decision_representation": "per-candidate-question/v1",
    }


def test_repeated_source_orders_do_not_manufacture_calibration_labels() -> None:
    result = validate_report({"rows": [_row("small", {"a": 1.0, "b": 0.0}, {"a": 1.0, "b": 0.0})]})
    assert result["calibration_labels"] == 2
    assert result["threshold"] is None
    assert result["raw_served"]["generated_scenarios"] == 32
    assert result["held_out_cascade"]["reference_batches"] == 0
    assert result["adoption_ready"] is False


def test_heldout_false_accept_can_change_selection_and_refusal_remains_fallback() -> None:
    labels = {str(i): float(i % 2) for i in range(10)}
    rows = [_row(str(i), labels, labels) for i in range(10)]
    rows.append(_row("wrong", {"a": 1.0, "b": 0.0, "c": 0.5}, {"a": 0.0, "b": 1.0, "c": 0.5}))
    rows.append(
        {"id": "refused", "reference": {"a": 1.0, "b": 0.0, "c": 0.5}, "provider_status": 429}
    )
    result = validate_report({"rows": rows})
    assert result["calibration_labels"] == 100
    assert result["threshold"] == 0.99
    cascade = result["held_out_cascade"]
    assert cascade["reference_batches"] == 2
    assert cascade["decision_batches_used"] == 1
    assert cascade["metrics"]["top1_exact"] < 1
    assert result["adoption_ready"] is False


def test_old_representation_cannot_supply_new_representation_labels() -> None:
    row = _row("old", {"a": 1.0}, {"a": 1.0})
    row.pop("decision_representation")
    with pytest.raises(ValueError, match="representation"):
        validate_report({"rows": [row]})
