"""Unit tests for folding the finalize grounding pass's LLM telemetry.

The real caller (``drain.persist_final_state``) always hands
``fold_grounding_telemetry`` an already-plain ``final_state`` -- its
own caller runs ``_plain_final_state`` first, which serializes
``metrics`` to a dict before drain ever sees it -- so these tests cover
that plain-dict shape, both empty and pre-populated.
"""

from __future__ import annotations

from typing import Any

from app.engine_adapter.drain.telemetry import fold_grounding_telemetry


def test_grounding_telemetry_is_folded_into_plain_metrics() -> None:
    """Non-empty usage merges into an existing plain-dict metrics field."""
    final_state: dict[str, Any] = {
        "metrics": {"llm_calls": 3, "model_usage": {}}
    }
    usage = {
        "claim_grounding::llm:test-model": {
            "calls": 5,
            "prompt_tokens": 50,
        }
    }

    fold_grounding_telemetry(final_state, usage)

    metrics = final_state["metrics"]
    assert metrics["llm_calls"] == 8
    entry = metrics["model_usage"]["claim_grounding::llm:test-model"]
    assert entry["calls"] == 5
    assert entry["prompt_tokens"] == 50


def test_grounding_telemetry_handles_missing_metrics_key() -> None:
    """A final_state with no prior metrics key still folds cleanly."""
    final_state: dict[str, Any] = {}
    usage = {"claim_grounding::llm:test-model": {"calls": 2}}

    fold_grounding_telemetry(final_state, usage)

    metrics = final_state["metrics"]
    assert metrics["llm_calls"] == 2


def test_a_grounding_pass_that_made_no_calls_charges_nothing() -> None:
    """A fully-reused grounding pass must not manufacture a metrics key."""
    final_state: dict[str, Any] = {"metrics": {"llm_calls": 4}}

    fold_grounding_telemetry(final_state, {})

    assert final_state["metrics"] == {"llm_calls": 4}
