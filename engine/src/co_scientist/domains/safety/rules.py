"""Bare danger nouns need context; regex alone cannot clear them.
Operational harm remains blocked, and unresolved context must abstain safely."""

from __future__ import annotations

import dataclasses
import enum
import re


def _patterns(*sources: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(s, re.IGNORECASE) for s in sources)


# Action patterns remain binding regardless of context; tolerate padded spelling
# and distant objects.
_PROHIBITED_CERTAIN = _patterns(
    r"\bweapon[\s-]?i[sz]e\b",
    r"\bweaponi[sz]ation\b",
    r"\benhance\b.{0,300}\b(transmissibility|lethality|virulence)\b",
    r"\b(construct|build|assemble|smuggle|deploy)\b.{0,40}"
    r"\b(nuclear|radiological)\b.{0,20}\b(device|weapon|bomb)\b",
    r"\b(design|build|construct|assemble)\b.{0,60}"
    r"\b(explosive device|explosive charge|pipe bomb)\b.{0,100}"
    r"\b(kill|casualt|crowded)\w*",
    # Weapon acquisition is Tier A: contextual Tier B resolution must not clear
    # operational requests.
    r"\b(make|making|obtain(ing)?|acquir(e|ing)|procur(e|ing)"
    r"|prepar(e|ing)|source|sourcing|purchase|purchasing)\b.{0,40}"
    r"\b(nerve agent|chemical weapon|bioweapon|biological weapon"
    r"|sarin|vx|tabun|novichok|anthrax|smallpox|ricin)\b",
    # Improvement is benign process language unless applied to a weapon's
    # effectiveness.
    r"\b(improv|increas|maximi[sz]|boost)\w*\b.{0,40}"
    r"\b(yield|potency|lethality|virulence|transmissibility|dispersal)\b"
    r".{0,60}\b(weapon|agent|bioweapon|toxin|pathogen)\b",
    # Weapon synthesis procedures are operational artifacts; Tier B precedence
    # would otherwise defer them.
    r"\b(step[- ]by[- ]step|detailed|complete|full)\b.{0,40}"
    r"\b(synthesis|protocol|procedure|route|recipe)\b.{0,60}"
    r"\b(nerve agent|nerve toxin|chemical weapon|bioweapon"
    r"|biological weapon|sarin|vx|tabun|novichok|ricin)\b",
    r"\b(synthesis|production) (route|protocol|procedure)\b.{0,40}"
    r"\b(nerve agent|nerve toxin|chemical weapon|bioweapon"
    r"|biological weapon|sarin|vx|tabun|novichok|ricin)\b",
)

_ETHICAL_CERTAIN = _patterns(
    r"\bnon[- ]consensual\b",
)

# Category-only danger needs contextual resolution instead of an unconditional
# block.
_PROHIBITED_CONTEXT = _patterns(
    r"\bmass[- ]casualty\b",
    r"\bbio[- ]?weapon\b",
    # Spelled-out weapon categories must be held just like their contracted
    # forms.
    r"\b(biological|chemical|radiological|nuclear) weapons?\b",
    r"\bnerve (agent|toxin)\b",
    r"\bnerve toxin agent\b",
)

_ETHICAL_CONTEXT = _patterns(
    r"\bwithout (informed )?consent\b",
    r"\beugenic",
)

# Operational intent outranks research framing; a hedge cannot excuse
# construction instructions.
_OPERATIONAL_INTENT_VERBS = _patterns(
    r"\bconstruct(ing|ed)?\b",
    r"\bbuild(ing)?\b",
    r"\bassembl(e|ing|ed)\b",
    r"\bdesign(ing|ed)?\b",
    r"\bdevelop(ing|ed)?\b",
    r"\bengineer(ing|ed)?\b",
    r"\bsynthesi[sz](e|ing|ed)\b",
    r"\bproduc(e|ing|ed)\b",
    r"\bmanufactur(e|ing|ed)\b",
    r"\bdeploy(ing|ed)?\b",
    r"\bweaponi[sz](e|ing|ed)\b",
    r"\benhanc(e|ing|ed)\b",
    r"\bcreat(e|ing|ed)\b",
    r"\bdispers(e|ing|ed)\b",
    r"\breleas(e|ing|ed)\b",
    r"\badminister(ing|ed)?\b",
    r"\bsmuggl(e|ing|ed)\b",
)

# Defensive markers only change a held reason; ambiguous words cannot clear
# danger matches.
_BENIGN_CONTEXT_MARKERS = _patterns(
    r"\breview(ing|s|ed)?\b",
    r"\banaly(?:z|s)(?:e|ing|ed|is)\b",
    r"\bassess(?:ing|ed|ment)?\b",
    r"\bevaluat(?:e|ing|ed|ion)\b",
    r"\bstud(?:y|ying|ied)\b",
    r"\binvestigat(?:e|ing|ed|ion)\b",
    r"\bexamin(?:e|ing|ed|ation)\b",
    r"\bcharacteriz(?:e|ing|ed)\b",
    r"\bhistor(?:y|ical)\b",
    r"\bdeclassified\b",
    r"\bcomplian(?:t|ce)\b",
    r"\bdiagnostic\b",
    r"\btriage\b",
    r"\bdisaster\b",
    r"\bverification\b",
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
# Obfuscation requires a sensitive hint plus hedging, never a bare-keyword
# block.
_SENSITIVE_HINT = _patterns(
    r"\b(pathogen|toxin|virus|agent|synthesis|anthrax|smallpox|ebola"
    r"|marburg|nerve agent|chemical weapon|bioweapon|nuclear|radiological"
    r"|radioactive|explosive|bomb)\b",
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


POLICY_VERSION = "coscientist-safety-v5"

REDACTED_PLACEHOLDER = "[REDACTED FOR SAFETY]"


class SafetyOutcome(str, enum.Enum):
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
    return outcome in BLOCKING_OUTCOMES


def is_blocking_status(status: str | None) -> bool:
    if not status:
        return False
    try:
        return SafetyOutcome(status) in BLOCKING_OUTCOMES
    except ValueError:
        return False


@dataclasses.dataclass(frozen=True)
class SafetyReview:
    """Contextual assessment may clear or block Tier B holds; Tier A verdicts
    remain binding.
    """

    outcome: SafetyOutcome
    reason: str
    matches: tuple[str, ...]
    policy_version: str
    needs_context: bool = False

    @property
    def blocks_tournament(self) -> bool:
        return self.outcome in BLOCKING_OUTCOMES

    def to_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "reason": self.reason,
            "matches": list(self.matches),
            "policy_version": self.policy_version,
            "needs_context": self.needs_context,
        }


@dataclasses.dataclass(frozen=True)
class ContentSafetyReview:
    decision: str
    category: str
    reason: str
    matches: tuple[str, ...]
    risk_domains: tuple[str, ...]
    requires_review: bool
    policy_version: str = POLICY_VERSION


def _all_matches(text: str, patterns: tuple[re.Pattern[str], ...]) -> tuple[str, ...]:
    return tuple(
        match.group(0) for pattern in patterns if (match := pattern.search(text or "")) is not None
    )


def review_content_safety(text: str, stage: str) -> ContentSafetyReview:
    if stage not in {"intake", "final"}:
        raise ValueError("stage must be 'intake' or 'final'")
    prohibited = _all_matches(text, _CONTENT_PROHIBITED)
    if prohibited:
        return ContentSafetyReview(
            decision="block",
            category="prohibited",
            reason=("Content matches a prohibited weaponization or mass-casualty policy rule."),
            matches=prohibited,
            risk_domains=("cbrn_weaponization",),
            requires_review=False,
        )
    dual_use = _all_matches(text, _CONTENT_DUAL_USE)
    if dual_use and stage == "final":
        return ContentSafetyReview(
            decision="redact",
            category="redacted",
            reason=("Dual-use content requires redaction and explicit oversight."),
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


def _first_match(text: str, patterns: tuple[re.Pattern[str], ...]) -> str | None:
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
    hit = _first_match(text, patterns)
    if hit is None:
        return None
    return SafetyReview(outcome, reason, (hit,), POLICY_VERSION)


_CERTAIN_CHECKS: tuple[tuple[tuple[re.Pattern[str], ...], SafetyOutcome, str], ...] = (
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

_CONTEXT_CHECKS: tuple[tuple[tuple[re.Pattern[str], ...], SafetyOutcome, str], ...] = (
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

_POST_OBFUSCATION_CHECKS: tuple[tuple[tuple[re.Pattern[str], ...], SafetyOutcome, str], ...] = (
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
    for patterns, outcome, reason in checks:
        review = _match_review(text, patterns, outcome, reason)
        if review is not None:
            return review
    return None


def _resolve_context_hit(text: str, hit: str, outcome: SafetyOutcome, reason: str) -> SafetyReview:
    """A finite verb list cannot prove benign intent; meta-research markers
    change the held reason only.
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
    for patterns, outcome, reason in _CONTEXT_CHECKS:
        hit = _first_match(text, patterns)
        if hit is not None:
            return _resolve_context_hit(text, hit, outcome, reason)
    return None


def _obfuscation_review(text: str) -> SafetyReview | None:
    obfuscation = _first_match(text, _OBFUSCATION)
    if obfuscation is None or _first_match(text, _SENSITIVE_HINT) is None:
        return None
    return SafetyReview(
        SafetyOutcome.UNCERTAIN,
        "obfuscated intent around sensitive content; manual review",
        (obfuscation,),
        POLICY_VERSION,
    )


def _review_after_certain_tier(text: str, detect_obfuscation: bool) -> SafetyReview:
    review = _obfuscation_review(text) if detect_obfuscation else None
    if review is not None:
        return review
    review = _first_tiered_review(text, _POST_OBFUSCATION_CHECKS)
    if review is not None:
        return review
    return SafetyReview(SafetyOutcome.ALLOW, "no safety concern detected", (), POLICY_VERSION)


def review_hypothesis_safety(text: str, *, detect_obfuscation: bool = True) -> SafetyReview:
    """`detect_obfuscation=False` is for whole documents: the hedge patterns
    carry no proximity bound, and a report's own footer states "for research
    purposes only", which any sensitive noun elsewhere would then complete.
    """
    review = _first_tiered_review(text, _CERTAIN_CHECKS)
    if review is not None:
        return review
    context_review = _first_context_review(text)
    if context_review is not None:
        return context_review
    return _review_after_certain_tier(text, detect_obfuscation)


def redact_hypothesis_fields(
    text: str | None,
    explanation: str | None,
    experiment: str | None,
    literature_grounding: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Every free-text field but the statement is hidden, so the hypothesis
    stays rankable while no screened detail survives a redact verdict.
    """
    return (
        text,
        REDACTED_PLACEHOLDER if explanation else explanation,
        REDACTED_PLACEHOLDER if experiment else experiment,
        REDACTED_PLACEHOLDER if literature_grounding else literature_grounding,
    )
