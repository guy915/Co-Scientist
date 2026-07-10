"""Claim-level grounding, entailment, and publication gating (Milestone 5).

The four-state citation label (``app/citations.py``) is a document-level audit
signal; it is *not* claim-level verification and must not be the meaning of
"verified" (PLAN.md M5). This module adds the claim-level layer the paper
requires (SSR §6, §7):

1. **Atomic claim extraction** — split a hypothesis / mechanism / experiment /
   report into atomic claims.
2. **Per-claim entailment** — for each claim, assess the retrieved evidence as
   SUPPORTS / CONTRADICTS / INSUFFICIENT, recording the exact supporting and
   contradicting passages and the assessor provenance. Lexical similarity is a
   *retrieval/fallback* signal only, never the meaning of "verified."
3. **Resolvability, separately** — whether a citation's source resolves
   (URL/metadata/retraction) is judged independently of whether it supports the
   claim.
4. **Publication gate** — an unsupported or contradicted *fundamental* claim
   cannot let a hypothesis rank/publish; clearly labeled speculation is allowed
   only under an explicit policy flag.

The default assessor is deterministic (a contradiction lexicon plus a lexical
support fallback) so the pipeline and its tests run offline; a real NLI/LLM
entailment model is a documented, swappable provenance-tagged assessor. Google
does not publish its entailment model or thresholds (SSR §12), so those are
documented clone choices.
"""

from __future__ import annotations

import dataclasses
import enum
import re

# --- Atomic claim extraction ------------------------------------------------

# A claim must have some substance; drop fragments below this word count.
_MIN_CLAIM_WORDS = 4
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def extract_atomic_claims(text: str) -> list[str]:
    """Split a passage into atomic claims (sentence-level), de-noised.

    Sentences shorter than ``_MIN_CLAIM_WORDS`` words (headings, fragments) are
    dropped. Order is preserved and duplicates removed, so the claim list is a
    stable, auditable decomposition of the source text.

    Args:
        text: The hypothesis / mechanism / experiment / report text.

    Returns:
        The atomic claims, in order of first appearance.
    """
    claims: list[str] = []
    seen: set[str] = set()
    for raw in _SENTENCE_SPLIT.split(text or ""):
        claim = raw.strip()
        if len(claim.split()) < _MIN_CLAIM_WORDS:
            continue
        key = claim.lower()
        if key in seen:
            continue
        seen.add(key)
        claims.append(claim)
    return claims


# --- Per-claim entailment ---------------------------------------------------


class EntailmentLabel(str, enum.Enum):
    """Structured claim-vs-evidence verdict (not a lexical-overlap bucket)."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    INSUFFICIENT = "insufficient"


# Phrases that flip a passage's polarity toward contradiction. Deterministic
# stand-in for an NLI contradiction signal; the real assessor is an LLM/NLI
# model (see assess_claim's ``assessor`` provenance).
_CONTRADICTION_MARKERS = (
    "no evidence",
    "not associated",
    "no association",
    "does not",
    "did not",
    "failed to",
    "contrary to",
    "contradicts",
    "refutes",
    "disproven",
    "no significant",
    "not significant",
    "ineffective",
)

# Clone-defined lexical support threshold used ONLY as a fallback retrieval
# signal (never the meaning of "verified").
_SUPPORT_LEXICAL_THRESHOLD = 0.18

_ASSESSOR_DETERMINISTIC = "deterministic-v1"


@dataclasses.dataclass(frozen=True)
class ClaimAssessment:
    """The entailment outcome for one claim against retrieved evidence."""

    claim: str
    label: EntailmentLabel
    supporting_passages: tuple[str, ...]
    contradicting_passages: tuple[str, ...]
    assessor: str

    @property
    def is_fundamental_failure(self) -> bool:
        """True when this claim is contradicted (a hard publication blocker)."""
        return self.label is EntailmentLabel.CONTRADICTS


def _tokens(text: str) -> frozenset[str]:
    """Content tokens (length > 3) for the lexical fallback signal."""
    return frozenset(t for t in text.lower().split() if len(t) > 3)


def _lexical_score(claim: str, passage: str) -> float:
    """Jaccard token overlap — a fallback retrieval signal, not a verdict."""
    a, b = _tokens(claim), _tokens(passage)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _passage_contradicts(claim: str, passage: str) -> bool:
    """True when a passage is topically related but carries a negation marker.

    Requires some lexical relatedness so an unrelated negative sentence does
    not count as contradicting this specific claim.
    """
    lowered = passage.lower()
    if not any(marker in lowered for marker in _CONTRADICTION_MARKERS):
        return False
    return _lexical_score(claim, passage) >= _SUPPORT_LEXICAL_THRESHOLD / 2


def assess_claim(
    claim: str,
    passages: list[str],
    *,
    assessor: str = _ASSESSOR_DETERMINISTIC,
    support_threshold: float = _SUPPORT_LEXICAL_THRESHOLD,
) -> ClaimAssessment:
    """Assess a claim against evidence passages, returning a structured verdict.

    Contradiction dominates: if any related passage negates the claim, the
    verdict is CONTRADICTS regardless of other support (a contradicted claim is
    a publication blocker). Otherwise a passage clearing the lexical support
    threshold yields SUPPORTS; nothing sufficient yields INSUFFICIENT. Every
    verdict records the exact passages that drove it and the assessor id, so
    the claim-evidence graph is auditable.

    Args:
        claim: The atomic claim being assessed.
        passages: Retrieved evidence passages (abstracts / snippets).
        assessor: Provenance id of the assessor (swap for an NLI/LLM model).
        support_threshold: Lexical fallback support threshold (clone default).

    Returns:
        The claim's :class:`ClaimAssessment`.
    """
    supporting: list[str] = []
    contradicting: list[str] = []
    for passage in passages:
        score = _lexical_score(claim, passage)
        if _passage_contradicts(claim, passage):
            contradicting.append(passage)
        elif score >= support_threshold:
            supporting.append(passage)

    if contradicting:
        label = EntailmentLabel.CONTRADICTS
    elif supporting:
        label = EntailmentLabel.SUPPORTS
    else:
        label = EntailmentLabel.INSUFFICIENT

    return ClaimAssessment(
        claim=claim,
        label=label,
        supporting_passages=tuple(supporting),
        contradicting_passages=tuple(contradicting),
        assessor=assessor,
    )


# --- Resolvability (independent of support) ---------------------------------


class Resolvability(str, enum.Enum):
    """Whether a citation's *source* resolves — separate from claim support."""

    RESOLVABLE = "resolvable"
    UNRESOLVABLE = "unresolvable"
    RETRACTED = "retracted"


@dataclasses.dataclass(frozen=True)
class CitationMetadata:
    """Source metadata the resolvability check inspects (not claim support)."""

    url: str = ""
    available: bool = True
    retracted: bool = False
    source_type: str = ""


def assess_resolvability(meta: CitationMetadata) -> Resolvability:
    """Judge whether a citation source resolves, independent of claim support.

    Retraction dominates (a retracted source is unusable even if reachable),
    then reachability. This separation is the M5 requirement: metadata/
    resolvability is verified apart from whether the source supports the claim.
    """
    if meta.retracted:
        return Resolvability.RETRACTED
    if not meta.available or not meta.url:
        return Resolvability.UNRESOLVABLE
    return Resolvability.RESOLVABLE


# --- Publication gate -------------------------------------------------------


class GateDecision(str, enum.Enum):
    """Whether a hypothesis may enter ranking / the final report."""

    ALLOW = "allow"
    BLOCK = "block"


@dataclasses.dataclass(frozen=True)
class GateResult:
    """The publication-gate outcome plus the claims that drove it."""

    decision: GateDecision
    reason: str
    contradicted_claims: tuple[str, ...]
    unsupported_claims: tuple[str, ...]


def publication_gate(
    assessments: list[ClaimAssessment],
    *,
    allow_speculative: bool = False,
) -> GateResult:
    """Decide whether a hypothesis may be published from its claim assessments.

    A hypothesis whose fundamental claims are contradicted must not rank or
    publish (BLOCK). Merely insufficient (unsupported-but-not-contradicted)
    claims block only when speculation is not explicitly permitted; with
    ``allow_speculative`` they pass so clearly labeled speculative claims are
    allowed under policy (SSR §7). A hypothesis with no claims is treated as
    unsupported.

    Args:
        assessments: The per-claim assessments for the hypothesis.
        allow_speculative: When True, INSUFFICIENT claims do not block (they
            are surfaced as speculative), but CONTRADICTS always blocks.

    Returns:
        The :class:`GateResult`.
    """
    contradicted = tuple(
        a.claim for a in assessments if a.label is EntailmentLabel.CONTRADICTS
    )
    unsupported = tuple(
        a.claim for a in assessments if a.label is EntailmentLabel.INSUFFICIENT
    )

    if contradicted:
        return GateResult(
            GateDecision.BLOCK,
            f"{len(contradicted)} fundamental claim(s) contradicted",
            contradicted,
            unsupported,
        )
    if not assessments:
        return GateResult(
            GateDecision.BLOCK,
            "no atomic claims could be assessed",
            contradicted,
            unsupported,
        )
    if unsupported and not allow_speculative:
        return GateResult(
            GateDecision.BLOCK,
            f"{len(unsupported)} claim(s) lack supporting evidence",
            contradicted,
            unsupported,
        )
    return GateResult(
        GateDecision.ALLOW,
        "all fundamental claims supported"
        if not unsupported
        else "supported; unsupported claims allowed as labeled speculation",
        contradicted,
        unsupported,
    )
