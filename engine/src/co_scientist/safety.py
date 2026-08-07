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

Design note -- "certainly prohibited" vs. "matched a sensitive pattern, needs
context" (see ``docs/fidelity-audit/FINDINGS.md`` J13): a regex can name two
different kinds of thing, and treating them the same is what produced both
the false-negative and the false-positive failure this module was rewritten
to fix.

- A pattern that names an *action* (a verb aimed at producing, enhancing, or
  deploying harm -- "weaponize", "enhance ... lethality", a construct/build
  verb next to a named weapon device) is evidence of intent regardless of
  the surrounding sentence: there is no legitimate research framing for an
  instruction to build the thing. These stay hard, unconditional blocks
  (``_PROHIBITED_CERTAIN`` / ``_ETHICAL_CERTAIN``).
- A pattern that only names a *category of danger* -- a bare noun phrase
  like "bioweapon", "mass casualty", "nerve agent", "eugenic" -- is evidence
  the text is *about* that category, not evidence it *proposes* to create or
  execute it. Historical scholarship, treaty-compliance review, disaster
  triage planning, and diagnostic/defensive research all use this vocabulary
  routinely. Treating the bare noun as terminal is what made the hard
  control split block disaster-response triage, detection assays,
  treaty-compliance history, and a research-ethics review -- five of six
  legitimate near-boundary items overall. These are corroborated against
  the rest of the sentence (``_PROHIBITED_CONTEXT`` / ``_ETHICAL_CONTEXT``,
  resolved by ``_resolve_context_hit``): an operational-intent verb nearby
  resolves the ambiguity toward "certainly prohibited" (so a hedge like
  "reviewing how to construct a bioweapon" cannot buy its way past the
  category check just by adding a research-sounding verb).
- Critical asymmetry, and the bug in an earlier version of this design: the
  operational-verb list is finite and an attacker picks the verb. "make",
  "obtain", "acquire", "prepare", "formulate" and any other verb outside
  the list are exactly as operational as "construct", so gating a *clear*
  on the absence of a listed verb loses that trade every time -- an earlier
  version of this module cleared a Tier B hit to ALLOW whenever a
  meta-research marker was present and no listed verb matched, which let
  "A historical review of how to make a nerve agent" and "Improve the
  yield of a bioweapon" both pass. **A Tier B category-only match is
  therefore never cleared to ALLOW by this layer, full stop, regardless of
  any meta-research marker.** Absent an operational verb, it resolves to
  UNCERTAIN (held for manual review) whether or not a meta-research marker
  is present -- the marker only changes the recorded *reason* text, never
  the outcome, since a meta-research framing is corroborating context for a
  human reviewer, not a machine-verifiable clearance. This is weaker than
  the false-positive fix this module originally shipped with (a genuinely
  benign hard-control item now reads UNCERTAIN, not ALLOW, and both are
  blocking outcomes) but it cannot be bypassed by vocabulary choice the way
  the ALLOW-clearing version could. Every Tier B verdict carries
  ``needs_context=True`` so a caller with a contextual model available may
  still raise it further (never lower it -- see the "model may raise,
  never lower" contract used elsewhere in this policy); UNCERTAIN is a
  hold, not a clear, and only human adjudication clears a hold.
- **The deterministic ALLOW this module returns is the final verdict on the
  engine's bulk hypothesis-generation path today.** ``app/app/engine_adapter
  /drain.py`` screens every engine-generated hypothesis with this module
  and nothing else -- no contextual model sits behind it there (see that
  module's own docstring). Only the app's scientist-authored-hypothesis
  admission path (``app/app/human_input.py``) escalates a held verdict to a
  model. Since Tier B can no longer produce ALLOW, this mostly matters for
  the plain no-match ALLOW and for Tier A: neither passes through any
  context check, so a gap in either is not caught by anything downstream on
  most of a run's hypotheses.
- What this does not fix: genuine paraphrase or synonym substitution (no
  literal trigger token at all) is outside what a regex layer can safely
  chase without turning into the whack-a-mole broadening that makes the
  false-positive rate worse. That gap is closed by contextual (LLM)
  escalation, not by widening these patterns further.

Two known coverage gaps in the *certain* tier were also closed here because
they had zero pattern at all, not because the match window needed
broadening: nuclear-device and mass-casualty-explosive-device construction
verb-plus-device combinations.
"""

from __future__ import annotations

import dataclasses
import enum
import re

from co_scientist.safety_patterns import (
    _BENIGN_CONTEXT_MARKERS as _BENIGN_CONTEXT_MARKERS,
)
from co_scientist.safety_patterns import (
    _CONTENT_DUAL_USE as _CONTENT_DUAL_USE,
)
from co_scientist.safety_patterns import (
    _CONTENT_PROHIBITED as _CONTENT_PROHIBITED,
)
from co_scientist.safety_patterns import (
    _DUAL_USE as _DUAL_USE,
)
from co_scientist.safety_patterns import (
    _ETHICAL_CERTAIN as _ETHICAL_CERTAIN,
)
from co_scientist.safety_patterns import (
    _ETHICAL_CONTEXT as _ETHICAL_CONTEXT,
)
from co_scientist.safety_patterns import (
    _OBFUSCATION as _OBFUSCATION,
)
from co_scientist.safety_patterns import (
    _OPERATIONAL_INTENT_VERBS as _OPERATIONAL_INTENT_VERBS,
)
from co_scientist.safety_patterns import (
    _PROHIBITED_CERTAIN as _PROHIBITED_CERTAIN,
)
from co_scientist.safety_patterns import (
    _PROHIBITED_CONTEXT as _PROHIBITED_CONTEXT,
)
from co_scientist.safety_patterns import (
    _REDACT as _REDACT,
)
from co_scientist.safety_patterns import (
    _SENSITIVE_HINT as _SENSITIVE_HINT,
)
from co_scientist.safety_patterns import (
    _patterns as _patterns,
)

POLICY_VERSION = "coscientist-safety-v4"

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


@dataclasses.dataclass(frozen=True)
class SafetyReview:
    """The structured safety review of one hypothesis, with provenance.

    ``needs_context`` marks a verdict produced by the Tier B category-only
    path (see the module docstring): a contextual model, when available,
    should still have the final say and may raise -- never lower -- this
    verdict. It is False for every Tier A ("certainly prohibited") verdict
    and for the plain no-match allow.
    """

    outcome: SafetyOutcome
    reason: str
    matches: tuple[str, ...]
    policy_version: str
    needs_context: bool = False

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
            "needs_context": self.needs_context,
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


# Checked, in order, before the context/obfuscation/dual-use/redact tiers.
_CERTAIN_CHECKS: tuple[
    tuple[tuple[re.Pattern[str], ...], SafetyOutcome, str], ...
] = (
    (
        _PROHIBITED_CERTAIN,
        SafetyOutcome.PROHIBITED,
        "matches a prohibited weaponization/mass-casualty pattern",
    ),
    (
        _ETHICAL_CERTAIN,
        SafetyOutcome.ETHICAL_CONCERN,
        "raises an ethical-norms concern",
    ),
)

# Checked after the certain tier, before obfuscation: category-only matches
# resolved by ``_resolve_context_hit`` rather than treated as terminal.
_CONTEXT_CHECKS: tuple[
    tuple[tuple[re.Pattern[str], ...], SafetyOutcome, str], ...
] = (
    (
        _PROHIBITED_CONTEXT,
        SafetyOutcome.PROHIBITED,
        "matches a prohibited weaponization/mass-casualty pattern",
    ),
    (
        _ETHICAL_CONTEXT,
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


def _resolve_context_hit(
    text: str, hit: str, outcome: SafetyOutcome, reason: str
) -> SafetyReview:
    """Corroborate a Tier B category-only match against the rest of the text.

    See the module docstring for the full reasoning, in particular why this
    never returns ALLOW: an operational-intent verb list is finite and an
    attacker picks the verb, so gating a *clear* on the absence of a listed
    verb is a bypass waiting for a synonym, not a safety property. An
    operational-intent verb anywhere in the text resolves the match toward
    the original ``outcome`` (block) -- there is no legitimate framing that
    excuses an instruction to build the thing. Absent that, a meta-research
    marker (or, absent even that, nothing at all) resolves to UNCERTAIN: held
    for manual review, never allowed through automatically. The marker only
    changes the recorded reason, since it is corroborating context for a
    human reviewer, not a machine-verifiable clearance.
    """
    if _first_match(text, _OPERATIONAL_INTENT_VERBS):
        return SafetyReview(outcome, reason, (hit,), POLICY_VERSION, True)
    if _first_match(text, _BENIGN_CONTEXT_MARKERS):
        return SafetyReview(
            SafetyOutcome.UNCERTAIN,
            (
                "matches a sensitive category term in an apparently "
                "descriptive/meta-research context; held for manual "
                "review, not cleared"
            ),
            (hit,),
            POLICY_VERSION,
            True,
        )
    return SafetyReview(
        SafetyOutcome.UNCERTAIN,
        (
            "matches a sensitive category term with no corroborating "
            "signal either way; held for manual review"
        ),
        (hit,),
        POLICY_VERSION,
        True,
    )


def _first_context_review(text: str) -> SafetyReview | None:
    """Return the first Tier B category-only match, resolved, or None."""
    for patterns, outcome, reason in _CONTEXT_CHECKS:
        hit = _first_match(text, patterns)
        if hit is not None:
            return _resolve_context_hit(text, hit, outcome, reason)
    return None


def _obfuscation_review(text: str) -> SafetyReview | None:
    """Return the UNCERTAIN verdict for obfuscated sensitive intent, or None."""
    obfuscation = _first_match(text, _OBFUSCATION)
    if obfuscation is None or _first_match(text, _SENSITIVE_HINT) is None:
        return None
    return SafetyReview(
        SafetyOutcome.UNCERTAIN,
        "obfuscated intent around sensitive content; manual review",
        (obfuscation,),
        POLICY_VERSION,
    )


def _review_after_certain_tier(text: str) -> SafetyReview:
    """Resolve everything checked after the Tier A/B tiers.

    Obfuscation, then dual-use/redact, then the default allow.
    """
    review = _obfuscation_review(text)
    if review is not None:
        return review
    review = _first_tiered_review(text, _POST_OBFUSCATION_CHECKS)
    if review is not None:
        return review
    return SafetyReview(
        SafetyOutcome.ALLOW, "no safety concern detected", (), POLICY_VERSION
    )


def review_hypothesis_safety(text: str) -> SafetyReview:
    """Review one hypothesis's text and return a structured safety outcome.

    Precedence (most severe first): certainly-prohibited (Tier A), a Tier B
    category-only match (never cleared to allow -- see the module
    docstring), obfuscated intent (uncertain), dual-use (allow with
    redact), sensitive operational detail (redact), else allow.

    Args:
        text: The hypothesis (and any mechanism/experiment) text.

    Returns:
        The :class:`SafetyReview`.
    """
    review = _first_tiered_review(text, _CERTAIN_CHECKS)
    if review is not None:
        return review
    context_review = _first_context_review(text)
    if context_review is not None:
        return context_review
    return _review_after_certain_tier(text)


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
