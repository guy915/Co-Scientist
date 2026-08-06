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
    """Structured claim-vs-evidence verdict (not a lexical-overlap bucket).

    ``PARTIAL`` is a middle support tier: the evidence bears on the claim and
    is consistent with it but stops short of full entailment (a near-miss). It
    counts as support for publication and the "Unverified" badge -- it means
    "we found relevant, consistent evidence", not "we found nothing" -- while
    staying distinct from ``SUPPORTS`` so a reader can tell full entailment
    from a partial match. Precedence when a claim draws several verdicts is
    contradicts > supports > partial > insufficient (see ``_entailment_label``
    in :mod:`app.claims`).
    """

    SUPPORTS = "supports"
    PARTIAL = "partial"
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
# offline (reads the supplied metadata); the engine drain's evidence-identity
# availability check instead calls the live resolver in
# app/citation_resolver.py, which actually dereferences the DOI/PMID/URL.
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
    """The publication-gate outcome plus the claims that drove it.

    Attributes:
        decision: Whether the hypothesis may publish.
        reason: The rule that decided it, in the gate's own words.
        contradicted_claims: Claims the evidence contradicts.
        unsupported_claims: Claims the evidence neither supports nor
            contradicts.
        speculative_claims: The ``unsupported_claims`` presented as
            speculation, which do not block on their own.
        failed_claims: The claims the block is actually about, chosen by
            :func:`_failed_claims`; empty on an ALLOW. Recorded verbatim as
            the ``claim_gate`` safety decision's matches, so the gate names
            them rather than leaving a caller to re-derive which of the
            other three tuples the reason referred to.
    """

    decision: GateDecision
    reason: str
    contradicted_claims: tuple[str, ...]
    unsupported_claims: tuple[str, ...]
    speculative_claims: tuple[str, ...] = ()
    failed_claims: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class _ClaimPartition:
    """One hypothesis's claims, split by what the gate does with each.

    Attributes:
        contradicted: Claims the evidence contradicts.
        unsupported: Claims the evidence neither supports nor contradicts.
        speculative: The ``unsupported`` claims presented as speculation.
        blocking_unsupported: The ``unsupported`` claims not covered by
            ``speculative``, which is what actually blocks.
    """

    contradicted: tuple[str, ...]
    unsupported: tuple[str, ...]
    speculative: tuple[str, ...]
    blocking_unsupported: tuple[str, ...]


def _classify_gate_claims(
    assessments: list[ClaimAssessment],
    *,
    allow_speculative: bool,
    explicitly_speculative_claims: Collection[str],
) -> _ClaimPartition:
    """Split claims into contradicted, unsupported, speculative, and blocking.

    Returns:
        The :class:`_ClaimPartition` the gate's rules are applied to.
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
    return _ClaimPartition(
        contradicted=contradicted,
        unsupported=unsupported,
        speculative=speculative,
        blocking_unsupported=blocking_unsupported,
    )


_SUPPORTING_LABELS = (EntailmentLabel.SUPPORTS, EntailmentLabel.PARTIAL)


def _blocks_for_missing_support(
    assessments: list[ClaimAssessment], *, require_supported_claim: bool
) -> bool:
    """Whether the gate blocks for lacking any evidence-supported claim.

    A ``PARTIAL`` verdict counts as support here (as it does for the badge):
    the claim has relevant, consistent evidence, so it does not leave the
    hypothesis wholly unsupported.
    """
    if not require_supported_claim:
        return False
    return not any(a.label in _SUPPORTING_LABELS for a in assessments)


def _gate_block_reason(
    assessments: list[ClaimAssessment],
    contradicted: tuple[str, ...],
    blocking_unsupported: tuple[str, ...],
    *,
    require_supported_claim: bool,
) -> str | None:
    """Return the reason to block, in priority order, or None to allow.

    Priority order: a contradicted fundamental claim blocks first, then a
    hypothesis with no assessable claims at all, then (when required) a
    hypothesis with no supported claim of any kind, then any categorical
    claim left unsupported once speculative claims are set aside.
    """
    if contradicted:
        return f"{len(contradicted)} fundamental claim(s) contradicted"
    if not assessments:
        return "no atomic claims could be assessed"
    if _blocks_for_missing_support(
        assessments, require_supported_claim=require_supported_claim
    ):
        return "no evidence-supported contextual claim"
    if blocking_unsupported:
        return f"{len(blocking_unsupported)} categorical claim(s) lack support"
    return None


def _failed_claims(partition: _ClaimPartition) -> tuple[str, ...]:
    """The claims a block is about, in the order the gate's rules fire.

    Mirrors :func:`_gate_block_reason`'s priority: a contradiction names the
    contradicted claims, otherwise the categorical claims left unsupported
    once speculation is set aside, and failing both (every unsupported claim
    was speculative, so the block was for having no supported claim at all)
    the unsupported claims themselves. A hypothesis with no assessable claims
    has nothing to name and yields an empty tuple.
    """
    return (
        partition.contradicted
        or partition.blocking_unsupported
        or partition.unsupported
    )


def _decide_gate(
    assessments: list[ClaimAssessment],
    partition: _ClaimPartition,
    *,
    require_supported_claim: bool,
) -> GateResult:
    """Apply the gate's blocking rules, in priority order, to the claims."""
    claims = (
        partition.contradicted,
        partition.unsupported,
        partition.speculative,
    )
    reason = _gate_block_reason(
        assessments,
        partition.contradicted,
        partition.blocking_unsupported,
        require_supported_claim=require_supported_claim,
    )
    if reason is not None:
        return GateResult(
            GateDecision.BLOCK,
            reason,
            *claims,
            failed_claims=_failed_claims(partition),
        )
    allow_reason = "all fundamental claims supported"
    if partition.unsupported:
        allow_reason = (
            "categorical claims supported; novel claims labeled speculative"
        )
    return GateResult(GateDecision.ALLOW, allow_reason, *claims)


def publication_gate(
    assessments: list[ClaimAssessment],
    *,
    allow_speculative: bool = False,
    explicitly_speculative_claims: Collection[str] = (),
    require_supported_claim: bool = False,
) -> GateResult:
    """Decide whether a hypothesis may be published from its claim assessments.

    A hypothesis whose fundamental claims are contradicted must not rank or
    publish (BLOCK). Merely insufficient claims block only when speculation
    is not explicitly permitted; with ``allow_speculative`` they pass so
    clearly labeled speculative claims are allowed under policy (SSR §7). A
    hypothesis with no claims is treated as unsupported.

    Args:
        assessments: The per-claim assessments for the hypothesis.
        allow_speculative: Compatibility switch treating every insufficient
            claim as speculative. Contradictions always block.
        explicitly_speculative_claims: Insufficient claims whose source text
            explicitly presents them as hypotheses/predictions/proposed
            experiments, so they don't masquerade as categorical findings.
        require_supported_claim: Whether at least one claim must have an
            evidence-supporting span before the proposal can pass.

    Returns:
        The :class:`GateResult`.
    """
    partition = _classify_gate_claims(
        assessments,
        allow_speculative=allow_speculative,
        explicitly_speculative_claims=explicitly_speculative_claims,
    )
    return _decide_gate(
        assessments,
        partition,
        require_supported_claim=require_supported_claim,
    )
