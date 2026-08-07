"""Compiled pattern tables for the per-hypothesis safety policy.

Split out of ``co_scientist.safety`` to keep that module within the
file-length ceiling. The two-tier split these tables encode -- patterns
naming an *action* versus patterns naming only a *category* -- is what
lets a category-only match be corroborated against the rest of the text
rather than treated as terminal; the reasoning lives in ``safety``'s own
module docstring, which is where a reader looking for the policy will
start.

Every name here is imported by ``safety`` and referenced unqualified
there, so monkeypatching ``co_scientist.safety._<NAME>`` in a test keeps
working exactly as before.
"""

from __future__ import annotations

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
)

_ETHICAL_CERTAIN = _patterns(
    r"\bnon[- ]consensual\b",
)

# Tier B -- "matched a sensitive pattern, needs context": the pattern names
# only a category of danger. Resolved by ``_resolve_context_hit`` rather
# than treated as terminal; see the module docstring.
_PROHIBITED_CONTEXT = _patterns(
    r"\bmass[- ]casualty\b",
    r"\bbioweapon\b",
    r"\bnerve agent\b",
    r"\bchemical weapon\b",
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
