"""Per-hypothesis safety review (Milestone 6).

The shared intake/final gates (``app/safety.py``) screen the *run goal* and the
*final report*. M6 adds the missing layer: a structured safety review of each
*individual hypothesis* before it enters the tournament and again after
material evolution/revision, so an unsafe hypothesis is removed from ranking and
synthesis rather than screened only at the run boundary (SSR §4 preliminary
safety, §10; RGV §9).

The review combines deterministic rules with a policy version stamp (a
model-based classifier is a swappable, provenance-tagged reviewer). Outcomes are
separated — ``prohibited`` / ``dual_use`` / ``ethical_concern`` / ``redact`` /
``allow`` / ``uncertain`` — and uncertainty routes to safe abstention (excluded
from the tournament, flagged for manual review) rather than being overridden by
a quality score. ``redact`` actually redacts the defined fields.

Google's exact classifier and its 1,200-goal adversarial set are private
(SSR §7, §12); the rules here are a documented, legally shareable clone.
"""

from __future__ import annotations

import dataclasses
import enum
import re

POLICY_VERSION = "hyp-safety-v1"

# Placeholder text a redacted field is replaced with.
REDACTED_PLACEHOLDER = "[REDACTED FOR SAFETY]"


class HypothesisSafetyOutcome(str, enum.Enum):
    """Structured per-hypothesis safety outcomes (separated, not one scalar)."""

    PROHIBITED = "prohibited"
    DUAL_USE = "dual_use"
    ETHICAL_CONCERN = "ethical_concern"
    REDACT = "redact"
    UNCERTAIN = "uncertain"
    ALLOW = "allow"


# Outcomes that exclude a hypothesis from the tournament and synthesis.
# UNCERTAIN is excluded: uncertainty routes to safe abstention, never
# optimistic inclusion (a quality score must not override safety).
_BLOCKING_OUTCOMES = frozenset(
    {
        HypothesisSafetyOutcome.PROHIBITED,
        HypothesisSafetyOutcome.ETHICAL_CONCERN,
        HypothesisSafetyOutcome.UNCERTAIN,
    }
)


def is_blocking_status(status: str | None) -> bool:
    """True when a persisted ``safety_status`` blocks tournament/synthesis.

    Lets consumers (e.g. the report path) act on the status recorded by the
    pre-tournament screen without re-running the review.
    """
    if not status:
        return False
    try:
        return HypothesisSafetyOutcome(status) in _BLOCKING_OUTCOMES
    except ValueError:
        return False


def _patterns(*sources: str) -> tuple[re.Pattern[str], ...]:
    """Compile case-insensitive patterns."""
    return tuple(re.compile(s, re.IGNORECASE) for s in sources)


# Narrow prohibited patterns: weaponization / mass-casualty intent. Deliberately
# specific to avoid blocking legitimate pathogen biology or CRISPR research.
_PROHIBITED = _patterns(
    r"\bweaponi[sz]e\b",
    r"\bweaponi[sz]ation\b",
    r"\bmass[- ]casualty\b",
    r"\bbioweapon\b",
    r"\bnerve agent\b",
    r"\bchemical weapon\b",
    r"\benhance\b.{0,40}\b(transmissibility|lethality|virulence)\b",
)

# Ethical-concern patterns: research contradicting disciplinary norms.
_ETHICAL = _patterns(
    r"\bwithout (informed )?consent\b",
    r"\bnon[- ]consensual\b",
    r"\beugenic",
)

# Dual-use markers: legitimate but sensitive; allowed with a redact/annotate.
_DUAL_USE = _patterns(
    r"\bdual[- ]use\b",
    r"\bselect agent\b",
    r"\bgain[- ]of[- ]function\b",
)

# Sensitive-operational markers: keep the hypothesis but redact detail fields.
_REDACT = _patterns(
    r"\bsynthesis (route|protocol)\b",
    r"\bstep[- ]by[- ]step\b.{0,30}\b(synthesis|protocol)\b",
)

# Obfuscation markers paired with a sensitive term signal a hidden intent that
# the reviewer cannot confidently clear -> UNCERTAIN (safe abstention).
_OBFUSCATION = _patterns(
    r"\b(for research purposes only|purely hypothetical(ly)?)\b",
    r"\byou know what i mean\b",
)
_SENSITIVE_HINT = _patterns(
    r"\b(pathogen|toxin|virus|agent|synthesis)\b",
)


@dataclasses.dataclass(frozen=True)
class HypothesisSafetyReview:
    """The structured safety review of one hypothesis, with provenance."""

    outcome: HypothesisSafetyOutcome
    reason: str
    matches: tuple[str, ...]
    policy_version: str

    @property
    def blocks_tournament(self) -> bool:
        """True when this hypothesis must be excluded from ranking/synthesis."""
        return self.outcome in _BLOCKING_OUTCOMES

    def to_dict(self) -> dict[str, object]:
        """Serialize for an access-controlled audit record."""
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


def review_hypothesis_safety(text: str) -> HypothesisSafetyReview:
    """Review one hypothesis's text and return a structured safety outcome.

    Precedence (most severe first): prohibited, ethical concern, obfuscated
    intent (uncertain → abstain), dual-use (allow with redact), sensitive
    operational detail (redact), else allow. Every review stamps the policy
    version so an audit trail records which policy produced the decision.

    Args:
        text: The hypothesis (and any mechanism/experiment) text.

    Returns:
        The :class:`HypothesisSafetyReview`.
    """
    if (hit := _first_match(text, _PROHIBITED)) is not None:
        return HypothesisSafetyReview(
            HypothesisSafetyOutcome.PROHIBITED,
            "matches a prohibited weaponization/mass-casualty pattern",
            (hit,),
            POLICY_VERSION,
        )
    if (hit := _first_match(text, _ETHICAL)) is not None:
        return HypothesisSafetyReview(
            HypothesisSafetyOutcome.ETHICAL_CONCERN,
            "raises an ethical-norms concern",
            (hit,),
            POLICY_VERSION,
        )
    obfuscation = _first_match(text, _OBFUSCATION)
    if obfuscation is not None and _first_match(text, _SENSITIVE_HINT):
        return HypothesisSafetyReview(
            HypothesisSafetyOutcome.UNCERTAIN,
            "obfuscated intent around sensitive content; manual review",
            (obfuscation,),
            POLICY_VERSION,
        )
    if (hit := _first_match(text, _DUAL_USE)) is not None:
        return HypothesisSafetyReview(
            HypothesisSafetyOutcome.DUAL_USE,
            "legitimate but dual-use; allow with redaction/annotation",
            (hit,),
            POLICY_VERSION,
        )
    if (hit := _first_match(text, _REDACT)) is not None:
        return HypothesisSafetyReview(
            HypothesisSafetyOutcome.REDACT,
            "contains sensitive operational detail to redact",
            (hit,),
            POLICY_VERSION,
        )
    return HypothesisSafetyReview(
        HypothesisSafetyOutcome.ALLOW,
        "no safety concern detected",
        (),
        POLICY_VERSION,
    )


def redact_fields(fields: dict[str, str]) -> dict[str, str]:
    """Redact the sensitive fields of a hypothesis (REDACT/DUAL_USE outcomes).

    Replaces the operational-detail fields (mechanism, experimental context)
    with a placeholder while keeping the high-level statement, so the decision
    is truthful — ``redact`` actually redacts (PLAN.md M6.3).

    Args:
        fields: A mapping of field name to value (e.g. mechanism, experiment).

    Returns:
        A new mapping with the sensitive fields replaced by the placeholder.
    """
    sensitive = {"mechanism", "experiment", "experimental_context"}
    return {
        key: (REDACTED_PLACEHOLDER if key in sensitive and value else value)
        for key, value in fields.items()
    }
