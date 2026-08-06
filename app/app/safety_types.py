"""The safety decision record, shared by the policy, model, and gate layers.

Homed away from ``app.safety`` so the deterministic policy, the contextual
model layer, the redaction helpers, and the run-level gate can all name the
same record without importing each other in a cycle. ``app.safety`` re-exports
every name here and remains the import surface for callers.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from co_scientist.safety import POLICY_VERSION

__all__ = ["SafetyDecision", "SafetyMode"]


class SafetyMode(str, enum.Enum):
    """How aggressively the safety filter treats dual-use content."""

    STANDARD = "standard"
    STRICT = "strict"


@dataclass
class SafetyDecision:
    """Outcome of a safety pass."""

    stage: str  # "intake" | "final"
    decision: str  # "allow" | "redact" | "hold" | "block"
    reason: str = ""
    matches: list[str] = field(default_factory=list)
    category: str = "allowed"
    policy_version: str = POLICY_VERSION
    risk_domains: list[str] = field(default_factory=list)
    requires_review: bool = False
    assessor: str = "deterministic"

    def to_dict(self) -> dict[str, str | list[str] | bool]:
        """Serialize this decision for the `safety.{stage}` event payload."""
        return {
            "stage": self.stage,
            "decision": self.decision,
            "reason": self.reason,
            "matches": self.matches,
            "category": self.category,
            "policy_version": self.policy_version,
            "risk_domains": self.risk_domains,
            "requires_review": self.requires_review,
            "assessor": self.assessor,
        }
