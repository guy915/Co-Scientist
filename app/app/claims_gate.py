"""Entailment verdict, resolvability, and publication gating for claims.

Split out of :mod:`app.claims`, which had grown past the module-size budget.
This module holds the lower half of that file: the entailment verdict enum, the
provenance support span and the claim-assessment record they populate, the
resolvability check (independent of claim support), and the publication gate.

:mod:`app.claims` imports these names back and re-exports them, so every public
name remains importable from ``app.claims`` exactly as before. This module
deliberately does **not** import :mod:`app.claims` -- doing so would create an
import cycle, since ``app.claims`` depends on the names defined here. The set
moved here is self-contained precisely so that no such back-import is needed.
"""

from __future__ import annotations

import dataclasses
import enum
from collections.abc import Callable, Collection

# --- Per-claim entailment verdict -------------------------------------------


class EntailmentLabel(str, enum.Enum):
    """Structured claim-vs-evidence verdict (not a lexical-overlap bucket)."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    INSUFFICIENT = "insufficient"


# --- Support spans (provenance) and claim assessments -----------------------


@dataclasses.dataclass(frozen=True)
class SupportSpan:
    """An exact evidence span an assessor cited for (or against) a claim.

    ``quote`` is the verbatim substring ``passage.text[start:end]``, so a
    reader can open the source and find the exact passage that grounds the
    verdict. Records the source evidence id and url for auditability.
    """

    evidence_id: str
    quote: str
    start: int
    end: int
    source: str = ""
    url: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serialize for the ``claim_evidence`` store and the API."""
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class ClaimAssessment:
    """The entailment outcome for one claim against retrieved evidence."""

    claim: str
    label: EntailmentLabel
    supporting_passages: tuple[SupportSpan, ...]
    contradicting_passages: tuple[SupportSpan, ...]
    assessor: str

    @property
    def is_fundamental_failure(self) -> bool:
        """True when this claim is contradicted (a hard publication blocker)."""
        return self.label is EntailmentLabel.CONTRADICTS


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
    doi: str = ""
    available: bool = True
    retracted: bool = False
    source_type: str = ""


# A resolver maps citation metadata to a resolvability verdict. The default is
# offline (reads the supplied metadata); a live resolver performs URL/DOI
# resolution and a retraction lookup (see app/citation_resolver.py).
Resolver = Callable[[CitationMetadata], Resolvability]


def offline_resolver(meta: CitationMetadata) -> Resolvability:
    """Judge resolvability from supplied metadata only (no network).

    Retraction dominates (a retracted source is unusable even if reachable),
    then reachability. This is the deterministic default so the pipeline and
    tests run offline.
    """
    if meta.retracted:
        return Resolvability.RETRACTED
    if not meta.available or not meta.url:
        return Resolvability.UNRESOLVABLE
    return Resolvability.RESOLVABLE


def assess_resolvability(
    meta: CitationMetadata, *, resolver: Resolver = offline_resolver
) -> Resolvability:
    """Judge whether a citation source resolves, independent of claim support.

    Delegates to the (swappable) ``resolver``. This separation is the M5
    requirement: metadata/resolvability is verified apart from whether the
    source supports the claim.
    """
    return resolver(meta)


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
    speculative_claims: tuple[str, ...] = ()


def publication_gate(
    assessments: list[ClaimAssessment],
    *,
    allow_speculative: bool = False,
    explicitly_speculative_claims: Collection[str] = (),
    require_supported_claim: bool = False,
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
        allow_speculative: Compatibility switch treating every insufficient
            claim as speculative. Contradictions always block.
        explicitly_speculative_claims: Insufficient claims whose source text
            explicitly presents them as hypotheses, predictions, or proposed
            experiments. They remain visible but do not masquerade as
            categorical findings.
        require_supported_claim: Whether at least one claim must have an
            evidence-supporting span before the proposal can pass.

    Returns:
        The :class:`GateResult`.
    """
    contradicted = tuple(
        a.claim for a in assessments if a.label is EntailmentLabel.CONTRADICTS
    )
    unsupported = tuple(
        a.claim for a in assessments if a.label is EntailmentLabel.INSUFFICIENT
    )
    speculative_set = set(explicitly_speculative_claims)
    speculative = tuple(
        claim
        for claim in unsupported
        if allow_speculative or claim in speculative_set
    )
    speculative_lookup = set(speculative)
    blocking_unsupported = tuple(
        claim for claim in unsupported if claim not in speculative_lookup
    )

    def _result(decision: GateDecision, reason: str) -> GateResult:
        return GateResult(
            decision, reason, contradicted, unsupported, speculative
        )

    if contradicted:
        return _result(
            GateDecision.BLOCK,
            f"{len(contradicted)} fundamental claim(s) contradicted",
        )
    if not assessments:
        return _result(GateDecision.BLOCK, "no atomic claims could be assessed")
    if require_supported_claim and not any(
        assessment.label is EntailmentLabel.SUPPORTS
        for assessment in assessments
    ):
        return _result(
            GateDecision.BLOCK, "no evidence-supported contextual claim"
        )
    if blocking_unsupported:
        return _result(
            GateDecision.BLOCK,
            f"{len(blocking_unsupported)} categorical claim(s) lack support",
        )
    return _result(
        GateDecision.ALLOW,
        "all fundamental claims supported"
        if not unsupported
        else "categorical claims supported; novel claims labeled speculative",
    )
