"""Lightweight safety filter for intake and final output.

Goals:
- Block obviously hazardous CBRN / weaponization asks at intake.
- Redact or annotate dual-use scientific content at final-output stage.
- Keep allow lists explicit; default to allow.
- Determinism: same input always yields the same decision.
"""

from __future__ import annotations

import enum
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from app import store
from app.config import settings
from app.store import RunStatus

logger = logging.getLogger(__name__)


class SafetyMode(str, enum.Enum):
    """How aggressively the safety filter treats dual-use content."""

    STANDARD = "standard"
    STRICT = "strict"


def _resolve_safety_mode() -> SafetyMode:
    """Coerce the configured safety mode, defaulting to STANDARD if invalid."""
    try:
        return SafetyMode(settings.safety_mode.lower())
    except ValueError:
        return SafetyMode.STANDARD


SAFETY_MODE = _resolve_safety_mode()

# Hard-block patterns: production of weaponized agents, mass-casualty intent.
# These are deliberately narrow keyword combinations to avoid blocking
# legitimate defensive / educational research.
_BLOCK_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(synthes(?:is|e|ize)|engineer|weaponize)\b.{0,40}"
        r"\b(nerve agent|sarin|vx|tabun|novichok)\b",
        r"\b(enhance|engineer|weaponize)\b.{0,40}"
        r"\b(smallpox|anthrax|ebola|marburg)\b.{0,40}"
        r"\b(transmiss|lethal|virulen)",
        r"\b(build|construct|assemble)\b.{0,40}\b(nuclear|radiological)\b"
        r".{0,20}\b(weapon|bomb|device)\b",
        r"\bgain[- ]of[- ]function\b.{0,40}\b(human-to-human|airborne)\b",
        r"\b(produce|manufacture)\b.{0,40}\b(fentanyl|methamphetamine)\b"
        r".{0,20}\b(scale|kilogram)\b",
    )
)

# Redact patterns: mark output as dual-use when present, but do not block.
_REDACT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(pathogen|toxin|virus|bacterium)\b.{0,30}"
        r"\b(transmiss|lethal|host range)\b",
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

    def to_dict(self) -> dict[str, str | list[str]]:
        """Serialize this decision for the `safety.{stage}` event payload."""
        return {
            "stage": self.stage,
            "decision": self.decision,
            "reason": self.reason,
            "matches": self.matches,
        }


def _scan(text: str, patterns: Iterable[re.Pattern[str]]) -> list[str]:
    """Return the matched substring for each pattern that hits `text`."""
    hits: list[str] = []
    for pat in patterns:
        # Only the first match per pattern is kept; `matches` is a diagnostic
        # trail for the safety decision, not an exhaustive occurrence count.
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
            reason=(
                "Input matches a hard-block pattern (weaponization or "
                "mass-casualty intent)."
            ),
            matches=blocked,
        )
    flagged = _scan(text, _REDACT_PATTERNS)
    # Unlike screen_final below, intake only redacts under strict mode: a
    # dual-use-sounding research goal is allowed through by default so a
    # run is not blocked purely on vocabulary before any content exists.
    if flagged and SAFETY_MODE == SafetyMode.STRICT:
        return SafetyDecision(
            stage="intake",
            decision="redact",
            reason=(
                "Input flagged dual-use; strict mode requires explicit "
                "oversight."
            ),
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
            reason=(
                "Generated report contains a hard-block pattern; "
                "refusing to publish."
            ),
            matches=blocked,
        )
    flagged = _scan(text, _REDACT_PATTERNS)
    # Final output always flags dual-use language, regardless of SAFETY_MODE:
    # a generated report is finished content, not an ambiguous ask, so it
    # gets the stricter treatment intake reserves for strict mode only.
    if flagged:
        return SafetyDecision(
            stage="final",
            decision="redact",
            reason=(
                "Output contains dual-use language; flagged for human review."
            ),
            matches=flagged,
        )
    return SafetyDecision(stage="final", decision="allow")


async def apply_safety_gate(
    run_id: str,
    result: SafetyDecision,
    emit: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    *,
    db_path: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Record a safety decision, emit it, and gate the run on a hard block.

    Shared by both workflow providers so the record -> emit -> block-and-stop
    sequence lives in one place. Yields the events to forward on the workflow's
    stream: the ``safety.{stage}`` decision, plus a blocked ``status`` event
    when the decision blocks. The caller must return from its workflow when
    ``result.decision == "block"``.

    Args:
        run_id: Identifier of the run being gated.
        result: The safety screening outcome to record and act on.
        emit: The provider's event emitter, called as ``emit(type, payload)``.
        db_path: Optional override for the SQLite database path.

    Yields:
        Event dicts to forward on the workflow's event stream.
    """
    store.add_safety_decision(
        run_id,
        result.stage,
        result.decision,
        result.reason,
        result.matches,
        db_path=db_path,
    )
    if result.decision == "block":
        logger.warning(
            "Safety gate blocked run %s at %s stage: %s",
            run_id,
            result.stage,
            result.reason,
        )
    else:
        logger.info(
            "Safety gate %s run %s at %s stage.",
            result.decision,
            run_id,
            result.stage,
        )
    yield await emit(f"safety.{result.stage}", result.to_dict())
    if result.decision == "block":
        store.update_run_status(
            run_id, RunStatus.BLOCKED, error=result.reason, db_path=db_path
        )
        yield await emit(
            "status", {"status": "blocked", "error": result.reason}
        )
