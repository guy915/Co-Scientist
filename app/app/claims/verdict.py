"""What a persisted claim-evidence edge's label and role mean.

``claim_evidence`` rows are read as plain dicts by the report gates, the
report body, the knowledge base and the claim gate, each asking a slightly
different question of the same two fields. This module is the one place those
questions are answered, so the vocabulary cannot drift between readers. The
questions are deliberately *not* one rule:

* :func:`is_supporting` -- ``partial`` counts, as it does for the "Unverified"
  badge and the claim gate (the rule itself is
  :attr:`~app.claims.gate.EntailmentLabel.is_supporting`).
* :func:`is_categorical_contradiction` -- the report withholds an idea only for
  a contradicted claim it presents as established fact; a contradicted
  *proposal* is a verdict on the idea, not a reason to hide it.
* :func:`is_contradicting` -- label alone, any role: the withheld-contradiction
  panel still lists a contradicted proposal.
* :func:`knowledge_kind` -- only a fully entailed or a contradicted claim is a
  durable knowledge-base row; ``partial`` asserts nothing settled.

Readers tolerate edges missing a label or role (legacy rows, partial dicts):
an unknown label is neither supporting nor contradicting, and a missing role
reads as categorical, the strict default. The persisted strings are unchanged
and the table carries no CHECK constraint on them.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from typing import Any

from app.claims.gate import EntailmentLabel

Edge = Mapping[str, Any]


class ClaimRole(str, enum.Enum):
    """How the source text presents a claim (``claim_evidence.claim_role``).

    ``CATEGORICAL`` claims are asserted as established fact and must be backed
    by evidence; ``SPECULATIVE`` ones are the idea's own proposal, where
    insufficient evidence is expected and a contradiction does not block.
    """

    CATEGORICAL = "categorical"
    SPECULATIVE = "speculative"


# The persisted default (the DDL's ``DEFAULT 'categorical'``) and the reading
# of a missing role: the strict one.
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
    """The edge's verdict, or ``None`` when it is missing or unrecognized."""
    try:
        return EntailmentLabel(edge.get("label"))
    except ValueError:
        return None


def role_of(edge: Edge) -> str:
    """The edge's claim role as persisted, defaulting to categorical."""
    return str(edge.get("claim_role") or DEFAULT_CLAIM_ROLE)


def is_speculative(role: str | None) -> bool:
    """Whether ``role`` marks a claim the idea only proposes."""
    return role == ClaimRole.SPECULATIVE


def is_supporting(edge: Edge) -> bool:
    """Whether the edge's evidence supports its claim (``partial`` counts)."""
    label = label_of(edge)
    return label is not None and label.is_supporting


def is_contradicting(edge: Edge) -> bool:
    """Whether the evidence contradicts the claim, whatever its role."""
    return label_of(edge) is EntailmentLabel.CONTRADICTS


def is_categorical_contradiction(edge: Edge) -> bool:
    """Whether the edge contradicts a claim presented as established fact."""
    return is_contradicting(edge) and not is_speculative(role_of(edge))


def is_excused(edge: Edge) -> bool:
    """Whether a lack of evidence is expected: a proposal, not a finding.

    Only an explicit ``insufficient`` verdict is excused. An edge with no
    label at all is not, though :func:`claim_status` reads it the same way.
    """
    return label_of(edge) is EntailmentLabel.INSUFFICIENT and is_speculative(
        role_of(edge)
    )


def claim_status(edge: Edge) -> str:
    """The reader-facing scientific status of one claim edge."""
    label = label_of(edge)
    if label is not None and label in _STATUS:
        return _STATUS[label]
    if is_speculative(role_of(edge)):
        return _STATUS_EXCUSED
    return _STATUS_UNSUPPORTED


def knowledge_kind(edge: Edge) -> str | None:
    """The knowledge-base row kind an edge becomes, or ``None`` if none.

    ``supports`` is a fact and ``contradicts`` a contradiction. ``partial``
    and ``insufficient`` assert nothing settled, so nothing is carried over.
    """
    label = label_of(edge)
    return None if label is None else _KNOWLEDGE_KIND.get(label)
