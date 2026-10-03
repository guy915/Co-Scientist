"""The safety decision record, shared by the policy, model, and gate layers."""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Any

from co_scientist.safety import POLICY_VERSION, REDACTED_PLACEHOLDER


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


def redact_matched_spans(text: str, matches: list[str]) -> str:
    """Replace every occurrence of each matched span with the placeholder.

    Matching is case-insensitive and literal: the spans come back from the
    policy as the text it matched, and the same phrase elsewhere in the
    document is the same disclosure.

    Args:
        text: The content to scrub.
        matches: The spans the safety policy matched.

    Returns:
        The content with every matched span replaced.
    """
    if not text:
        return text
    out = text
    for span in matches:
        if not span:
            continue
        out = re.sub(re.escape(span), REDACTED_PLACEHOLDER, out, flags=re.I)
    return out


def redact_payload_text(value: Any, matches: list[str]) -> Any:
    """Redact matched spans throughout a nested JSON-shaped payload.

    The report payload and the report markdown are two renderings of the same
    content, so scrubbing one and publishing the other would leave the
    original readable through the API and the report event.

    Args:
        value: A payload value: dict, list, string, or scalar.
        matches: The spans the safety policy matched.

    Returns:
        The value with every string leaf redacted; scalars are returned as-is.
    """
    if isinstance(value, str):
        return redact_matched_spans(value, matches)
    if isinstance(value, dict):
        return {
            key: redact_payload_text(item, matches)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payload_text(item, matches) for item in value]
    return value


__all__ = [
    "REDACTED_PLACEHOLDER",
    "SafetyDecision",
    "SafetyMode",
    "redact_matched_spans",
    "redact_payload_text",
]
