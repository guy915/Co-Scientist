"""Lightweight safety filter for intake and final output.

Goals:
- Block obviously hazardous CBRN / weaponization asks at intake.
- Redact or annotate dual-use scientific content at final-output stage.
- Keep allow lists explicit; default to allow.
- Determinism: same input always yields the same decision.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

SAFETY_MODE = os.getenv("SAFETY_MODE", "standard").lower()


# Hard-block patterns: production of weaponized agents, mass-casualty intent.
# These are deliberately narrow keyword combinations to avoid blocking legitimate
# defensive / educational research.
_BLOCK_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(synthes(?:is|e|ize)|engineer|weaponize)\b.{0,40}\b(nerve agent|sarin|vx|tabun|novichok)\b",
        r"\b(enhance|engineer|weaponize)\b.{0,40}\b(smallpox|anthrax|ebola|marburg)\b.{0,40}\b(transmiss|lethal|virulen)",
        r"\b(build|construct|assemble)\b.{0,40}\b(nuclear|radiological)\b.{0,20}\b(weapon|bomb|device)\b",
        r"\bgain[- ]of[- ]function\b.{0,40}\b(human-to-human|airborne)\b",
        r"\b(produce|manufacture)\b.{0,40}\b(fentanyl|methamphetamine)\b.{0,20}\b(scale|kilogram)\b",
    )
)

# Redact patterns: mark output as dual-use when present, but do not block.
_REDACT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(pathogen|toxin|virus|bacterium)\b.{0,30}\b(transmiss|lethal|host range)\b",
        r"\b(cbrn|chem-bio|bio-?weapon)\b",
        r"\b(dual[- ]use|select agent)\b",
    )
)


@dataclass
class SafetyDecision:
    """Outcome of a safety pass."""

    stage: str  # "intake" | "final"
    decision: str  # "allow" | "redact" | "block"
    reason: str = ""
    matches: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "decision": self.decision,
            "reason": self.reason,
            "matches": self.matches,
        }


def _scan(text: str, patterns: Iterable[re.Pattern[str]]) -> list[str]:
    hits: list[str] = []
    for pat in patterns:
        m = pat.search(text or "")
        if m:
            hits.append(m.group(0))
    return hits


def screen_intake(goal: str) -> SafetyDecision:
    """Run the input gate. Returns block / redact / allow."""
    text = goal or ""
    blocked = _scan(text, _BLOCK_PATTERNS)
    if blocked:
        return SafetyDecision(
            stage="intake",
            decision="block",
            reason="Input matches a hard-block pattern (weaponization or mass-casualty intent).",
            matches=blocked,
        )
    flagged = _scan(text, _REDACT_PATTERNS)
    if flagged and SAFETY_MODE == "strict":
        return SafetyDecision(
            stage="intake",
            decision="redact",
            reason="Input flagged dual-use; strict mode requires explicit oversight.",
            matches=flagged,
        )
    return SafetyDecision(stage="intake", decision="allow")


def screen_final(report_markdown: str) -> SafetyDecision:
    """Final-output gate. Block on hard hits; annotate dual-use otherwise."""
    text = report_markdown or ""
    blocked = _scan(text, _BLOCK_PATTERNS)
    if blocked:
        return SafetyDecision(
            stage="final",
            decision="block",
            reason="Generated report contains a hard-block pattern; refusing to publish.",
            matches=blocked,
        )
    flagged = _scan(text, _REDACT_PATTERNS)
    if flagged:
        return SafetyDecision(
            stage="final",
            decision="redact",
            reason="Output contains dual-use language; flagged for human review.",
            matches=flagged,
        )
    return SafetyDecision(stage="final", decision="allow")
