"""Reusing claim verdicts whose inputs have not moved.

A hypothesis's claims are assessed twice in a run: once at the pre-ranking
evidence gate, and again during the final drain. Between those points most
hypotheses do not change, so the second pass re-derives verdicts the first
already produced -- with an LLM assessor behind them.

Two properties make reuse safe, and both are properties of
``claims.assess_claim`` rather than assumptions about the run:

*Claims are independent.* A claim is assessed on its own, so its verdict
does not depend on which other claims were in the batch. That is what lets
the drain reuse a verdict the gate produced even though the two passes
assess different claim sets -- the gate reads the hypothesis's experiment
field as well, so it assesses a strict superset.

*Only retrieved evidence can move a verdict.* The assessor is never shown
the whole pool; ``assess_claim`` retrieves the top-k passages for that
claim and assesses against those alone. So a fingerprint covers the claim,
its role, the assessor, and only its own retrieved passages.

That scoping is what makes reuse worth having rather than merely correct.
Fingerprinting against the whole pool -- which the gate used to do -- means
any new article anywhere invalidates every stored verdict, and since the
drain runs after a run has finished retrieving evidence, it would have
reused nothing.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.claims import retrieve_passages
from app.claims_assessor import _DEFAULT_RETRIEVAL_TOP_K
from app.claims_gate import ClaimAssessment, EntailmentLabel, SupportSpan


@dataclasses.dataclass(frozen=True)
class ClaimRecord:
    """One atomic claim and the role it plays in its hypothesis."""

    claim: str
    role: str


def _passage_identity(passage: Any) -> dict[str, str]:
    """Return the fields of a passage that can move a verdict."""
    return {
        "evidence_id": str(passage.evidence_id),
        "text": str(passage.text),
        "source": str(passage.source),
        "url": str(passage.url),
    }


def claim_fingerprint(
    record: ClaimRecord,
    passages: Sequence[Any],
    assessor_id: str,
    top_k: int = _DEFAULT_RETRIEVAL_TOP_K,
) -> str:
    """Hash one claim and only the evidence that can reach its verdict.

    Runs the same retrieval ``assess_claim`` performs, so the digest covers
    exactly the assessor's input rather than an approximation of it.

    Args:
        record: The claim and the role it carries.
        passages: The run's full evidence pool, scoped per claim here.
        assessor_id: Provenance id of the assessor that would run.
        top_k: Retrieval budget, matching ``assess_claim``'s own.

    Returns:
        A hex digest identifying this claim's assessment inputs.
    """
    payload = {
        "assessor": assessor_id,
        "claim": record.claim,
        "role": record.role,
        "evidence": [
            _passage_identity(passage)
            for passage in retrieve_passages(
                record.claim, passages, top_k=top_k
            )
        ],
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def claims_fingerprint(
    records: Sequence[ClaimRecord],
    passages: Sequence[Any],
    assessor_id: str,
) -> str:
    """Hash a whole hypothesis's claim inputs, for the gate's own cache.

    Built from the per-claim digests so the two levels cannot disagree
    about what counts as a change.
    """
    return hashlib.sha256(
        json.dumps(
            [
                claim_fingerprint(record, passages, assessor_id)
                for record in records
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _span_from_dict(payload: Mapping[str, Any]) -> SupportSpan:
    """Rebuild one cited evidence span from its stored form."""
    return SupportSpan(
        evidence_id=str(payload.get("evidence_id") or ""),
        quote=str(payload.get("quote") or ""),
        start=int(payload.get("start") or 0),
        end=int(payload.get("end") or 0),
        source=str(payload.get("source") or ""),
        url=str(payload.get("url") or ""),
    )


def _spans_from(
    payload: Mapping[str, Any], key: str
) -> tuple[SupportSpan, ...]:
    """Rebuild one side's cited spans from a stored claim record."""
    return tuple(
        _span_from_dict(span)
        for span in payload.get(key) or ()
        if isinstance(span, Mapping)
    )


def _restore_one(
    record: Mapping[str, Any], assessor_id: str
) -> ClaimAssessment | None:
    """Rebuild one stored claim verdict, or None when it is unusable."""
    claim = str(record.get("claim") or "")
    label = str(record.get("label") or "")
    if not claim or label not in {item.value for item in EntailmentLabel}:
        return None
    return ClaimAssessment(
        claim=claim,
        label=EntailmentLabel(label),
        supporting_passages=_spans_from(record, "supporting_passages"),
        contradicting_passages=_spans_from(record, "contradicting_passages"),
        assessor=assessor_id,
    )


def reusable_assessments(
    gate_record: Mapping[str, Any] | None,
) -> dict[str, ClaimAssessment]:
    """Index a stored gate verdict's claims by their input fingerprint.

    A record missing its per-claim fingerprint is skipped rather than
    guessed at: it was written before fingerprints were stored, and reusing
    it would assert a verdict is current against inputs nobody recorded.

    Args:
        gate_record: The hypothesis's stored ``claim_gate`` enrichment.

    Returns:
        Fingerprint to assessment, for whatever is safely reusable.
    """
    if not gate_record:
        return {}
    assessor_id = str(gate_record.get("assessor") or "")
    reusable: dict[str, ClaimAssessment] = {}
    for record in gate_record.get("claims") or ():
        if not isinstance(record, Mapping):
            continue
        fingerprint = str(record.get("fingerprint") or "")
        restored = _restore_one(record, assessor_id) if fingerprint else None
        if restored is not None:
            reusable[fingerprint] = restored
    return reusable
