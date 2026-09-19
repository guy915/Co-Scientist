"""Summaries of observed model usage, distinct from static cost estimates."""

import copy
import math
from collections import Counter
from typing import Any


def summarize_usage(usage: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Retain raw telemetry and expose missing evidence, including old records.

    Estimated cost is complete only when every physical call has observed
    model identity, reported token counts and a static pricing entry. Even
    that is not a provider billing receipt. Empty telemetry proves neither
    free execution nor absence of inference.
    """
    calls = sum(int(row.get("calls", 0)) for row in usage.values())
    missing = {
        label: sum(
            max(0, int(row.get("calls", 0)) - _evidenced_calls(row, field))
            for row in usage.values()
        )
        for label, field in (
            ("unobserved_model_calls", "observed_model_calls"),
            ("unreported_usage_calls", "reported_usage_calls"),
            ("unpriced_calls", "priced_usage_calls"),
        )
    }
    requested: Counter[str] = Counter()
    for row in usage.values():
        requested.update(row.get("requested_models", {}))
    partial_estimate = sum(
        float(row["cost_usd"]) for row in usage.values() if _valid_cost(row)
    )
    complete = calls > 0 and not any(missing.values())
    return {
        "model_usage": copy.deepcopy(usage),
        "physical_calls": calls,
        "requested_models": dict(sorted(requested.items())),
        "observed_models": sorted(
            {
                key.split("::", 1)[-1]
                for key, row in usage.items()
                if row.get("observed_model_calls", 0) > 0
            }
        ),
        **missing,
        "has_usage_records": bool(usage),
        "estimate_complete": complete,
        "estimated_total_usd": round(partial_estimate, 6) if complete else None,
        "partial_estimated_total_usd": round(partial_estimate, 6),
        "billed_total_usd": None,
        "cost_basis": "static_estimate_not_billing_receipt",
    }


def _valid_cost(row: dict[str, Any]) -> bool:
    value = row.get("cost_usd")
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _evidenced_calls(row: dict[str, Any], field: str) -> int:
    if field == "priced_usage_calls" and not _valid_cost(row):
        return 0
    value = int(row.get(field, 0))
    return value if 0 <= value <= int(row.get("calls", 0)) else 0
