"""Application adapter for the engine-canonical hypothesis safety policy.

The engine owns the versioned classifier used before tournaments. The app uses
the same implementation for manual admission, persistence, and publication so
there is one policy definition rather than two regex copies that can drift.
"""

from __future__ import annotations

from co_scientist.safety import (
    POLICY_VERSION,
    REDACTED_PLACEHOLDER,
    SafetyOutcome,
    SafetyReview,
    is_blocking_status,
    review_hypothesis_safety,
)

# Compatibility names retained for existing API/store callers. They are aliases
# of the canonical engine types, not parallel policy implementations.
HypothesisSafetyOutcome = SafetyOutcome
HypothesisSafetyReview = SafetyReview


def redact_fields(fields: dict[str, str]) -> dict[str, str]:
    """Redact operational hypothesis fields under the canonical policy."""
    sensitive = {"mechanism", "experiment", "experimental_context"}
    return {
        key: (REDACTED_PLACEHOLDER if key in sensitive and value else value)
        for key, value in fields.items()
    }


__all__ = [
    "POLICY_VERSION",
    "REDACTED_PLACEHOLDER",
    "HypothesisSafetyOutcome",
    "HypothesisSafetyReview",
    "is_blocking_status",
    "redact_fields",
    "review_hypothesis_safety",
]
