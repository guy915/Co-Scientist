"""Bare danger nouns need context; regex alone cannot clear them.
Operational harm remains blocked, and unresolved context must abstain safely."""

from __future__ import annotations

import dataclasses
import enum
import re


def _patterns(*sources: str) -> tuple[re.Pattern[str], ...]:
    """Compile case-insensitive patterns."""
    return tuple(re.compile(s, re.IGNORECASE) for s in sources)


# Tier A -- "certainly prohibited": the pattern names an action, not just a
# category, so no surrounding context clears it. The spacing-tolerant
# weaponize pattern defeats a padded-out "weapon ize" evasion that a plain
# ``\bweaponi[sz]e\b`` word boundary misses; the enhance/lethality window is
# widened well past the original 40 chars so a multi-clause description of
# the same enhancement (capsid remodeling, receptor-binding optimization,
# ...) between the verb and its object still matches. The nuclear-device and
# explosive-device patterns are new coverage for weapon classes the reviewer
# previously had no pattern for at all.
_PROHIBITED_CERTAIN = _patterns(
    r"\bweapon[\s-]?i[sz]e\b",
    r"\bweaponi[sz]ation\b",
    r"\benhance\b.{0,300}\b(transmissibility|lethality|virulence)\b",
    r"\b(construct|build|assemble|smuggle|deploy)\b.{0,40}"
    r"\b(nuclear|radiological)\b.{0,20}\b(device|weapon|bomb)\b",
    r"\b(design|build|construct|assemble)\b.{0,60}"
    r"\b(explosive device|explosive charge|pipe bomb)\b.{0,100}"
    r"\b(kill|casualt|crowded)\w*",
    # Acquisition and preparation, named against a weapon *category*. These
    # belong in Tier A rather than among the corroborating verbs below
    # because of what Tier B now permits: a Tier B hold is resolvable by a
    # contextual model in either direction, so anything left in Tier B is
    # only as safe as that model's judgment. "How to make a nerve agent",
    # "improve the yield of a bioweapon" and "methods to obtain a chemical
    # weapon" are not judgment calls -- they are the request itself, and
    # every one of them sat in Tier B until this pattern existed, because
    # "make", "obtain" and "acquire" are absent from the operational-verb
    # list (that list being finite is the documented reason a *clear* can
    # never be gated on it). Naming the object as well as the verb is what
    # keeps this off the legitimate near-boundary items: a detection assay,
    # a treaty-compliance record and a disaster-triage protocol contain no
    # verb of acquisition applied to the weapon itself.
    r"\b(make|making|obtain(ing)?|acquir(e|ing)|procur(e|ing)"
    r"|prepar(e|ing)|source|sourcing|purchase|purchasing)\b.{0,40}"
    r"\b(nerve agent|chemical weapon|bioweapon|biological weapon"
    r"|sarin|vx|tabun|novichok|anthrax|smallpox|ricin)\b",
    # Yield/potency improvement is the operational act even though
    # "improve" is deliberately absent from every other list here: it is
    # ordinary process language ("improving triage protocols") until it is
    # applied to a weapon's effectiveness, which is what naming both the
    # measure and the object pins down.
    r"\b(improv|increas|maximi[sz]|boost)\w*\b.{0,40}"
    r"\b(yield|potency|lethality|virulence|transmissibility|dispersal)\b"
    r".{0,60}\b(weapon|agent|bioweapon|toxin|pathogen)\b",
    # A synthesis procedure named against a weapon class. Tier B would put
    # this to a contextual assessor, and it is not a question a reader
    # needs to weigh: "a step-by-step synthesis protocol for the nerve
    # agent" is the operational artifact itself. (``_REDACT`` also matches
    # the step-by-step phrasing, but Tier B is checked first and would
    # have resolved it, so the coverage has to be here.)
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

# Tier B -- "matched a sensitive pattern, needs context": the pattern names
# only a category of danger. Resolved by ``_resolve_context_hit`` rather
# than treated as terminal; see the module docstring.
_PROHIBITED_CONTEXT = _patterns(
    r"\bmass[- ]casualty\b",
    r"\bbio[- ]?weapon\b",
    # "biological weapon" and "nerve toxin agent" are the same categories
    # spelled out, and both walked past a layer that knew only the
    # contracted forms -- "Engineer a biological weapon capable of causing
    # casualties across an entire city" matched nothing at all. Naming a
    # category is Tier B, so widening it holds for context rather than
    # blocking outright; the operational verb in that sentence is what
    # then resolves it upward.
    r"\b(biological|chemical|radiological|nuclear) weapons?\b",
    r"\bnerve (agent|toxin)\b",
    r"\bnerve toxin agent\b",
)

_ETHICAL_CONTEXT = _patterns(
    r"\bwithout (informed )?consent\b",
    r"\beugenic",
)

# Corroborating signals for Tier B. An operational-intent verb resolves a
# category-only match toward "certainly prohibited" regardless of any
# meta-research marker also present, so a hedge like "reviewing how to
# construct a bioweapon" cannot buy its way past the category check just by
# adding a research-sounding verb.
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

# Meta-research / defensive framing. IMPORTANT: this list no longer has any
# power to clear a Tier B match to ALLOW (see _resolve_context_hit and the
# module docstring) -- its only effect is which reason string a held
# UNCERTAIN verdict carries, never whether it is held. That still makes a
# bad entry worth avoiding (a misleading "descriptive/meta-research" reason
# on an operational sentence is a real, if lower-stakes, defect for a human
# reviewer), so every entry is required to pass: "could this word appear in
# a sentence that is straightforwardly asking to do the dangerous thing?"
# Four entries failed that test and were removed, not just downgraded:
#   - "improve"/"improving": improving a weapon's yield or lethality IS the
#     operational act ("Improve the yield of a bioweapon"), not a
#     meta-research framing. (This is not moved to the operational-verb
#     list either -- it also appears in genuinely benign process language,
#     e.g. "improving hospital triage protocols", and that list's verbs are
#     unconditional Tier A blocks when paired with a weapon-device pattern,
#     which "improve" is specific enough to misfire on.)
#   - "training": a straightforwardly dangerous request routinely uses this
#     exact word ("training materials on chemical weapon acquisition").
#   - "policy": ambiguous between arms-control/treaty policy (benign) and an
#     organization's own operational doctrine for acquiring or using a
#     weapon (not benign) -- the word alone does not distinguish them.
#   - "detection"/"surveillance": both read as legitimate defensive framing
#     in isolation but are standard vocabulary for evasion/operational
#     planning too ("detection evasion", "surveillance to obtain a chemical
#     weapon covertly").
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
# Widened past the original single-purpose word list so the obfuscation tier
# (which already requires this hint to co-occur with a hedging phrase, so
# widening it does not add a bare-keyword block on its own) catches the
# weapon-class nouns it previously had no coverage for at all.
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
