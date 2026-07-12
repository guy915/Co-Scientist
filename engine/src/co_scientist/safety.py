"""Per-hypothesis safety classifier (engine-canonical).

Deterministic regex-based safety review of individual hypotheses. The engine
runs this before ranking so an unsafe hypothesis never enters the tournament,
evolution parent set, meta-review, or final report.

Outcomes are separated: ``prohibited`` / ``dual_use`` / ``ethical_concern`` /
``redact`` / ``uncertain`` / ``allow``. Blocking outcomes (prohibited, ethical
concern, uncertain) exclude from the pool entirely. ``uncertain`` routes to
safe abstention (held for manual review), not optimistic inclusion.

The app layer has a parallel copy (``app/app/hypothesis_safety.py``) that
predates this module; a follow-up should consolidate on this engine-canonical
version so the two cannot drift.
"""

from __future__ import annotations

import dataclasses
import enum
import re

POLICY_VERSION = "hyp-safety-v1"

REDACTED_PLACEHOLDER = "[REDACTED FOR SAFETY]"


class SafetyOutcome(str, enum.Enum):
    """Structured per-hypothesis safety outcomes."""

    PROHIBITED = "prohibited"
    DUAL_USE = "dual_use"
    ETHICAL_CONCERN = "ethical_concern"
    REDACT = "redact"
    UNCERTAIN = "uncertain"
    ALLOW = "allow"


BLOCKING_OUTCOMES = frozenset(
    {
        SafetyOutcome.PROHIBITED,
        SafetyOutcome.ETHICAL_CONCERN,
        SafetyOutcome.UNCERTAIN,
    }
)


def is_blocking(outcome: SafetyOutcome) -> bool:
    """True when this outcome excludes a hypothesis from ranking/synthesis."""
    return outcome in BLOCKING_OUTCOMES


def is_blocking_status(status: str | None) -> bool:
    """True when a persisted status string blocks tournament/synthesis."""
    if not status:
        return False
    try:
        return SafetyOutcome(status) in BLOCKING_OUTCOMES
    except ValueError:
        return False


def _patterns(*sources: str) -> tuple[re.Pattern[str], ...]:
    """Compile case-insensitive patterns."""
    return tuple(re.compile(s, re.IGNORECASE) for s in sources)


_PROHIBITED = _patterns(
    r"\bweaponi[sz]e\b",
    r"\bweaponi[sz]ation\b",
    r"\bmass[- ]casualty\b",
    r"\bbioweapon\b",
    r"\bnerve agent\b",
    r"\bchemical weapon\b",
    r"\benhance\b.{0,40}\b(transmissibility|lethality|virulence)\b",
)

_ETHICAL = _patterns(
    r"\bwithout (informed )?consent\b",
    r"\bnon[- ]consensual\b",
    r"\beugenic",
)

_DUAL_USE = _patterns(
    r"\bdual[- ]use\b",
    r"\bselect agent\b",
    r"\bgain[- ]of[- ]function\b",
)

_REDACT = _patterns(
    r"\bsynthesis (route|protocol)\b",
    r"\bstep[- ]by[- ]step\b.{0,30}\b(synthesis|protocol)\b",
)

_OBFUSCATION = _patterns(
    r"\b(for research purposes only|purely hypothetical(ly)?)\b",
    r"\byou know what i mean\b",
)
_SENSITIVE_HINT = _patterns(
    r"\b(pathogen|toxin|virus|agent|synthesis)\b",
)


@dataclasses.dataclass(frozen=True)
class SafetyReview:
    """The structured safety review of one hypothesis, with provenance."""

    outcome: SafetyOutcome
    reason: str
    matches: tuple[str, ...]
    policy_version: str

    @property
    def blocks_tournament(self) -> bool:
        """True when this hypothesis must be excluded from ranking."""
        return self.outcome in BLOCKING_OUTCOMES

    def to_dict(self) -> dict[str, object]:
        """Serialize for an audit record."""
        return {
            "outcome": self.outcome.value,
            "reason": self.reason,
            "matches": list(self.matches),
            "policy_version": self.policy_version,
        }


def _first_match(
    text: str, patterns: tuple[re.Pattern[str], ...]
) -> str | None:
    """Return the first matched substring, or None."""
    for pattern in patterns:
        m = pattern.search(text)
        if m:
            return m.group(0)
    return None


def review_hypothesis_safety(text: str) -> SafetyReview:
    """Review one hypothesis's text and return a structured safety outcome.

    Precedence (most severe first): prohibited, ethical concern, obfuscated
    intent (uncertain), dual-use (allow with redact), sensitive operational
    detail (redact), else allow.

    Args:
        text: The hypothesis (and any mechanism/experiment) text.

    Returns:
        The :class:`SafetyReview`.
    """
    if (hit := _first_match(text, _PROHIBITED)) is not None:
        return SafetyReview(
            SafetyOutcome.PROHIBITED,
            "matches a prohibited weaponization/mass-casualty pattern",
            (hit,),
            POLICY_VERSION,
        )
    if (hit := _first_match(text, _ETHICAL)) is not None:
        return SafetyReview(
            SafetyOutcome.ETHICAL_CONCERN,
            "raises an ethical-norms concern",
            (hit,),
            POLICY_VERSION,
        )
    obfuscation = _first_match(text, _OBFUSCATION)
    if obfuscation is not None and _first_match(text, _SENSITIVE_HINT):
        return SafetyReview(
            SafetyOutcome.UNCERTAIN,
            "obfuscated intent around sensitive content; manual review",
            (obfuscation,),
            POLICY_VERSION,
        )
    if (hit := _first_match(text, _DUAL_USE)) is not None:
        return SafetyReview(
            SafetyOutcome.DUAL_USE,
            "legitimate but dual-use; allow with redaction/annotation",
            (hit,),
            POLICY_VERSION,
        )
    if (hit := _first_match(text, _REDACT)) is not None:
        return SafetyReview(
            SafetyOutcome.REDACT,
            "contains sensitive operational detail to redact",
            (hit,),
            POLICY_VERSION,
        )
    return SafetyReview(
        SafetyOutcome.ALLOW,
        "no safety concern detected",
        (),
        POLICY_VERSION,
    )


def redact_hypothesis_fields(
    text: str | None,
    explanation: str | None,
    experiment: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Redact operational-detail fields for DUAL_USE/REDACT outcomes.

    Returns:
        The (text, explanation, experiment) tuple with sensitive fields
        replaced by the placeholder. Text is kept; explanation and experiment
        are redacted.
    """
    return (
        text,
        REDACTED_PLACEHOLDER if explanation else explanation,
        REDACTED_PLACEHOLDER if experiment else experiment,
    )
