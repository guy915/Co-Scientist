"""Per-hypothesis safety classifier (engine-canonical).

Deterministic regex-based safety review of individual hypotheses. The engine
runs this before ranking so an unsafe hypothesis never enters the tournament,
evolution parent set, meta-review, or final report.

Outcomes are separated: ``prohibited`` / ``dual_use`` / ``ethical_concern`` /
``redact`` / ``uncertain`` / ``allow``. Blocking outcomes (prohibited, ethical
concern, uncertain) exclude from the pool entirely. ``uncertain`` routes to
safe abstention (held for manual review), not optimistic inclusion.

The app imports this module for intake, hypothesis admission, and final-output
decisions, then adds semantic adjudication and persistence at its boundary.
"""

from __future__ import annotations

import dataclasses
import enum
import re

POLICY_VERSION = "coscientist-safety-v3"

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

_CONTENT_PROHIBITED = _patterns(
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
_CONTENT_DUAL_USE = _patterns(
    r"\b(pathogen|toxin|virus|bacterium)\b.{0,30}"
    r"\b(transmiss|lethal|host range)\b",
    r"\b(cbrn|chem-bio|bio-?weapon)\b",
    r"\b(dual[- ]use|select agent)\b",
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


@dataclasses.dataclass(frozen=True)
class ContentSafetyReview:
    """Canonical deterministic intake/final-content policy decision."""

    decision: str
    category: str
    reason: str
    matches: tuple[str, ...]
    risk_domains: tuple[str, ...]
    requires_review: bool
    policy_version: str = POLICY_VERSION


def _all_matches(
    text: str, patterns: tuple[re.Pattern[str], ...]
) -> tuple[str, ...]:
    """Return the first match from every canonical policy pattern."""
    return tuple(
        match.group(0)
        for pattern in patterns
        if (match := pattern.search(text or "")) is not None
    )


def review_content_safety(
    text: str, stage: str, *, strict_intake: bool = False
) -> ContentSafetyReview:
    """Apply the shared deterministic policy to intake or final content."""
    if stage not in {"intake", "final"}:
        raise ValueError("stage must be 'intake' or 'final'")
    prohibited = _all_matches(text, _CONTENT_PROHIBITED)
    if prohibited:
        return ContentSafetyReview(
            decision="block",
            category="prohibited",
            reason=(
                "Content matches a prohibited weaponization or "
                "mass-casualty policy rule."
            ),
            matches=prohibited,
            risk_domains=("cbrn_weaponization",),
            requires_review=False,
        )
    dual_use = _all_matches(text, _CONTENT_DUAL_USE)
    if dual_use and (stage == "final" or strict_intake):
        return ContentSafetyReview(
            decision="redact",
            category="redacted",
            reason=(
                "Dual-use content requires redaction and explicit oversight."
            ),
            matches=dual_use,
            risk_domains=("dual_use",),
            requires_review=True,
        )
    return ContentSafetyReview(
        decision="allow",
        category="allowed",
        reason="",
        matches=(),
        risk_domains=(),
        requires_review=False,
    )


def _first_match(
    text: str, patterns: tuple[re.Pattern[str], ...]
) -> str | None:
    """Return the first matched substring, or None."""
    for pattern in patterns:
        m = pattern.search(text)
        if m:
            return m.group(0)
    return None


def _match_review(
    text: str,
    patterns: tuple[re.Pattern[str], ...],
    outcome: SafetyOutcome,
    reason: str,
) -> SafetyReview | None:
    """Build a SafetyReview from the first pattern match, or None."""
    hit = _first_match(text, patterns)
    if hit is None:
        return None
    return SafetyReview(outcome, reason, (hit,), POLICY_VERSION)


# Checked, in order, before the obfuscation/dual-use/redact tiers below.
_PRE_OBFUSCATION_CHECKS: tuple[
    tuple[tuple[re.Pattern[str], ...], SafetyOutcome, str], ...
] = (
    (
        _PROHIBITED,
        SafetyOutcome.PROHIBITED,
        "matches a prohibited weaponization/mass-casualty pattern",
    ),
    (
        _ETHICAL,
        SafetyOutcome.ETHICAL_CONCERN,
        "raises an ethical-norms concern",
    ),
)

# Checked, in order, after the obfuscation tier, before the default allow.
_POST_OBFUSCATION_CHECKS: tuple[
    tuple[tuple[re.Pattern[str], ...], SafetyOutcome, str], ...
] = (
    (
        _DUAL_USE,
        SafetyOutcome.DUAL_USE,
        "legitimate but dual-use; allow with redaction/annotation",
    ),
    (
        _REDACT,
        SafetyOutcome.REDACT,
        "contains sensitive operational detail to redact",
    ),
)


def _first_tiered_review(
    text: str,
    checks: tuple[tuple[tuple[re.Pattern[str], ...], SafetyOutcome, str], ...],
) -> SafetyReview | None:
    """Return the first matching tier's SafetyReview, or None."""
    for patterns, outcome, reason in checks:
        review = _match_review(text, patterns, outcome, reason)
        if review is not None:
            return review
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
    review = _first_tiered_review(text, _PRE_OBFUSCATION_CHECKS)
    if review is not None:
        return review

    obfuscation = _first_match(text, _OBFUSCATION)
    if obfuscation is not None and _first_match(text, _SENSITIVE_HINT):
        return SafetyReview(
            SafetyOutcome.UNCERTAIN,
            "obfuscated intent around sensitive content; manual review",
            (obfuscation,),
            POLICY_VERSION,
        )

    review = _first_tiered_review(text, _POST_OBFUSCATION_CHECKS)
    if review is not None:
        return review

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
