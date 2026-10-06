from __future__ import annotations

import dataclasses
import enum
from collections.abc import Collection, Mapping
from typing import Any


class EntailmentLabel(str, enum.Enum):
    """Partial support grounds claims; contradiction takes precedence."""

    SUPPORTS = "supports"
    PARTIAL = "partial"
    CONTRADICTS = "contradicts"
    INSUFFICIENT = "insufficient"

    @property
    def is_supporting(self) -> bool:
        return self is EntailmentLabel.SUPPORTS or self is EntailmentLabel.PARTIAL


@dataclasses.dataclass(frozen=True)
class SupportSpan:
    """The quote must equal passage_text[start:end], so provenance is
    mechanically checkable.
    """

    evidence_id: str
    quote: str
    start: int
    end: int
    source: str = ""
    url: str = ""

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class ClaimAssessment:
    """Requested assessor identity and actual verification method differ;
    legacy missing metadata remains unknown.
    """

    claim: str
    label: EntailmentLabel
    supporting_passages: tuple[SupportSpan, ...]
    contradicting_passages: tuple[SupportSpan, ...]
    assessor: str
    verification_method: str = "legacy_unknown"

    @property
    def is_fundamental_failure(self) -> bool:
        return self.label is EntailmentLabel.CONTRADICTS


class GateDecision(str, enum.Enum):
    ALLOW = "allow"
    BLOCK = "block"


@dataclasses.dataclass(frozen=True)
class GateResult:
    """Failed claims come from the decisive gate rule, rather than a second
    approximation of that rule.
    """

    decision: GateDecision
    reason: str
    contradicted_claims: tuple[str, ...]
    unsupported_claims: tuple[str, ...]
    speculative_claims: tuple[str, ...] = ()
    failed_claims: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class _ClaimPartition:
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
    """Speculative allowances excuse missing support only, never categorical
    contradictions.
    """
    contradicted = tuple(a.claim for a in assessments if a.label is EntailmentLabel.CONTRADICTS)
    unsupported = tuple(a.claim for a in assessments if a.label is EntailmentLabel.INSUFFICIENT)
    speculative_set = set(explicitly_speculative_claims)
    speculative = tuple(
        claim for claim in unsupported if allow_speculative or claim in speculative_set
    )
    speculative_lookup = set(speculative)
    blocking_unsupported = tuple(claim for claim in unsupported if claim not in speculative_lookup)
    blocking_contradicted = tuple(claim for claim in contradicted if claim not in speculative_set)
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
    if blocking_contradicted:
        return f"{len(blocking_contradicted)} fundamental claim(s) contradicted"
    if not assessments:
        return "no atomic claims could be assessed"
    if _blocks_for_missing_support(assessments, require_supported_claim=require_supported_claim):
        return "no evidence-supported contextual claim"
    if blocking_unsupported:
        return f"{len(blocking_unsupported)} categorical claim(s) lack support"
    return None


def _failed_claims(partition: _ClaimPartition) -> tuple[str, ...]:
    """Failure priority follows the decisive gate rule, including
    speculative contradiction allowances.
    """
    return (
        partition.blocking_contradicted or partition.blocking_unsupported or partition.unsupported
    )


def _decide_gate(
    assessments: list[ClaimAssessment],
    partition: _ClaimPartition,
    *,
    require_supported_claim: bool,
) -> GateResult:
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
    """An allowed proposal contradiction remains a named finding, not a
    clean pass.
    """
    notes = []
    if partition.contradicted:
        notes.append(f"{len(partition.contradicted)} proposed claim(s) contradicted")
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
    """Categorical contradictions block publication; speculative proposals
    can publish with explicit evidence limitations.
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


Edge = Mapping[str, Any]


class ClaimRole(str, enum.Enum):
    CATEGORICAL = "categorical"
    SPECULATIVE = "speculative"


# Legacy missing roles default to strict categorical treatment.
DEFAULT_CLAIM_ROLE = ClaimRole.CATEGORICAL.value

KNOWLEDGE_FACT = "fact"
KNOWLEDGE_CONTRADICTION = "contradiction"

_KNOWLEDGE_KIND = {
    EntailmentLabel.SUPPORTS: KNOWLEDGE_FACT,
    EntailmentLabel.CONTRADICTS: KNOWLEDGE_CONTRADICTION,
}

_STATUS = {
    EntailmentLabel.SUPPORTS: "Supported",
    EntailmentLabel.PARTIAL: "Partially supported",
    EntailmentLabel.CONTRADICTS: "Contradicted",
}
_STATUS_EXCUSED = "Speculative — evidence insufficient"
_STATUS_UNSUPPORTED = "Unsupported categorical claim"


def label_of(edge: Edge) -> EntailmentLabel | None:
    try:
        return EntailmentLabel(edge.get("label"))
    except ValueError:
        return None


def role_of(edge: Edge) -> str:
    return str(edge.get("claim_role") or DEFAULT_CLAIM_ROLE)


def is_speculative(role: str | None) -> bool:
    return role == ClaimRole.SPECULATIVE


def is_supporting(edge: Edge) -> bool:
    label = label_of(edge)
    return label is not None and label.is_supporting


def is_contradicting(edge: Edge) -> bool:
    return label_of(edge) is EntailmentLabel.CONTRADICTS


def is_categorical_contradiction(edge: Edge) -> bool:
    return is_contradicting(edge) and not is_speculative(role_of(edge))


def is_excused(edge: Edge) -> bool:
    """Unknown historical labels are not equivalent to explicitly
    insufficient evidence.
    """
    return label_of(edge) is EntailmentLabel.INSUFFICIENT and is_speculative(role_of(edge))


def claim_status(edge: Edge) -> str:
    label = label_of(edge)
    if label is not None and label in _STATUS:
        return _STATUS[label]
    if is_speculative(role_of(edge)):
        return _STATUS_EXCUSED
    return _STATUS_UNSUPPORTED


def knowledge_kind(edge: Edge) -> str | None:
    """Partial support is not a settled fact."""
    label = label_of(edge)
    return None if label is None else _KNOWLEDGE_KIND.get(label)
