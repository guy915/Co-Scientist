"""Entailment verdict, resolvability, and publication gating for claims.

Split out of :mod:`app.claims`, which had grown past the module-size budget.
This module holds the lower half of that file: the entailment verdict enum, the
provenance support span and the claim-assessment record they populate, and the
publication gate. Citation metadata and resolvability -- a third concern, and
one no gate here consults -- moved on to :mod:`app.citation_metadata`.

:mod:`app.claims` imports these names back and re-exports the ones callers
use, so they remain importable from ``app.claims`` as before. This module
deliberately does **not** import :mod:`app.claims` -- doing so would create an
import cycle, since ``app.claims`` depends on the names defined here. The set
moved here is self-contained precisely so that no such back-import is needed.
"""

from __future__ import annotations

import dataclasses
import enum
from collections.abc import Collection

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

    @property
    def is_supporting(self) -> bool:
        """Whether this verdict counts as support: ``SUPPORTS`` or ``PARTIAL``.

        The one definition of the rule; :mod:`app.claim_verdict` lifts it onto
        persisted claim-evidence edges.
        """
        return (
            self is EntailmentLabel.SUPPORTS or self is EntailmentLabel.PARTIAL
        )


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
    """The entailment outcome and decision path, not scientific validation.

    ``assessor`` names the requested assessor; ``verification_method`` records
    the path actually taken. Missing historical metadata stays unknown.
    """

    claim: str
    label: EntailmentLabel
    supporting_passages: tuple[SupportSpan, ...]
    contradicting_passages: tuple[SupportSpan, ...]
    assessor: str
    verification_method: str = "legacy_unknown"

    @property
    def is_fundamental_failure(self) -> bool:
        """True when this claim is contradicted (a hard publication blocker)."""
        return self.label is EntailmentLabel.CONTRADICTS


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
        blocking_contradicted: The ``contradicted`` claims the hypothesis
            asserts as established fact, which is the contradiction that
            actually blocks.
    """

    contradicted: tuple[str, ...]
    unsupported: tuple[str, ...]
    speculative: tuple[str, ...]
    blocking_unsupported: tuple[str, ...]
    blocking_contradicted: tuple[str, ...]


def _classify_gate_claims(
    assessments: list[ClaimAssessment],
    *,
    allow_speculative: bool,
    explicitly_speculative_claims: Collection[str],
) -> _ClaimPartition:
    """Split claims into contradicted, unsupported, speculative, and blocking.

    Note the asymmetry between the two blocking sets. An *unsupported* claim
    is excused by ``allow_speculative`` as well as by its declared role,
    since that switch exists to say "this caller treats every insufficient
    claim as speculation". A *contradicted* claim is excused only by the
    declared role: ``allow_speculative`` is a blanket setting the pre-ranking
    gate passes True, so honoring it here would delete contradiction blocking
    from that call site entirely rather than make it role-aware.

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
    blocking_contradicted = tuple(
        claim for claim in contradicted if claim not in speculative_set
    )
    return _ClaimPartition(
        contradicted=contradicted,
        unsupported=unsupported,
        speculative=speculative,
        blocking_unsupported=blocking_unsupported,
        blocking_contradicted=blocking_contradicted,
    )


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
    return not any(a.label.is_supporting for a in assessments)


def _gate_block_reason(
    assessments: list[ClaimAssessment],
    blocking_contradicted: tuple[str, ...],
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
    if blocking_contradicted:
        return f"{len(blocking_contradicted)} fundamental claim(s) contradicted"
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
    contradicted claims the block was actually about -- the ones the
    hypothesis asserts as fact, not a contradicted proposal the gate just
    decided to tolerate -- otherwise the categorical claims left unsupported
    once speculation is set aside, and failing both (every unsupported claim
    was speculative, so the block was for having no supported claim at all)
    the unsupported claims themselves. A hypothesis with no assessable claims
    has nothing to name and yields an empty tuple.
    """
    return (
        partition.blocking_contradicted
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
        partition.blocking_contradicted,
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
    return GateResult(GateDecision.ALLOW, _allow_reason(partition), *claims)


def _allow_reason(partition: _ClaimPartition) -> str:
    """Say what an allowing gate tolerated, not merely that it allowed.

    Reached only when nothing categorical was contradicted, so any
    contradiction left here is on a claim the hypothesis merely proposes.
    Those pass -- the contradiction is a verdict on the proposal, which is
    the report's business rather than grounds to hide it -- but the reason
    has to name them, or the recorded decision reads as a clean pass over
    evidence that pointed the other way.
    """
    notes = []
    if partition.contradicted:
        notes.append(
            f"{len(partition.contradicted)} proposed claim(s) contradicted"
        )
    if partition.unsupported:
        notes.append("novel claims labeled speculative")
    if not notes:
        return "all fundamental claims supported"
    return "categorical claims supported; " + "; ".join(notes)


def publication_gate(
    assessments: list[ClaimAssessment],
    *,
    allow_speculative: bool = False,
    explicitly_speculative_claims: Collection[str] = (),
    require_supported_claim: bool = False,
) -> GateResult:
    """Decide whether a hypothesis may be published from its claim assessments.

    A hypothesis whose fundamental claims are contradicted must not rank or
    publish (BLOCK). "Fundamental" is a claim's declared role, not any claim
    it happens to carry: contradicting a claim the hypothesis asserts as
    established fact -- its literature grounding and mechanism -- blocks,
    while contradicting the idea it merely proposes is a verdict on that
    proposal and publishes with it. Merely insufficient claims block only
    when speculation is not explicitly permitted; with ``allow_speculative``
    they pass so clearly labeled speculative claims are allowed under policy
    (SSR §7). A hypothesis with no claims is treated as unsupported.

    Args:
        assessments: The per-claim assessments for the hypothesis.
        allow_speculative: Compatibility switch treating every insufficient
            claim as speculative. Deliberately does *not* reach
            contradictions: it is a blanket setting the pre-ranking gate
            passes True, so honoring it there would leave that call site
            with no contradiction blocking at all. Only a claim named in
            ``explicitly_speculative_claims`` may be contradicted and pass.
        explicitly_speculative_claims: Claims whose source text explicitly
            presents them as hypotheses/predictions/proposed experiments, so
            they don't masquerade as categorical findings. Excuses both an
            insufficient verdict and a contradicted one.
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
