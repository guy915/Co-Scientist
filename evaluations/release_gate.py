"""Artifact admission requires evidence of final screening; live unsupported
ideas may publish unverified. Provenance and verified-claim ratios are
observations, not extra publication gates.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from app.hypothesis.safety import is_blocking_status, review_hypothesis_safety
from app.report.gates import (
    EXCLUDED_HYPOTHESIS_STATUSES,
    contradicted_hypothesis_ids,
)

_REQUIRED_PROVENANCE = ("model", "policy_version", "retrieval_sources")


def _releasable(
    hypotheses: list[dict[str, Any]], contradicted: set[str]
) -> list[dict[str, Any]]:
    return [
        hyp
        for hyp in hypotheses
        if hyp.get("status") not in EXCLUDED_HYPOTHESIS_STATUSES
        and str(hyp.get("id")) not in contradicted
        and _passes_hypothesis_safety(hyp)
    ]


def _passes_hypothesis_safety(hyp: dict[str, Any]) -> bool:
    status = hyp.get("safety_status")
    if status and status != "pending":
        return not is_blocking_status(str(status))
    statement = hyp.get("statement")
    if not isinstance(statement, str) or not statement.strip():
        return False
    return not review_hypothesis_safety(statement).blocks_tournament


def _safety_reasons(safety: list[dict[str, Any]]) -> list[str]:
    """Approval of an old hold is not proof of a successful new final screen."""
    finals = [item for item in safety if item.get("stage") == "final"]
    if not finals:
        return ["missing final safety screen"]
    if any(type(item.get("id")) is not int for item in finals):
        return ["invalid final safety record identity"]
    final = max(finals, key=lambda item: item["id"])
    return _final_safety_reasons(final)


def _final_safety_reasons(final: dict[str, Any]) -> list[str]:
    decision = final.get("decision")
    if decision == "allow":
        return []
    if decision == "redact" and final.get("matches"):
        return []
    return ["final safety screen withheld publication"]


def _verified_claim_ratio(claims: list[dict[str, Any]]) -> float:
    if not claims:
        return 0.0
    supported = sum(1 for claim in claims if claim.get("label") == "supports")
    return supported / len(claims)


def _missing_provenance(provenance: dict[str, Any]) -> list[str]:
    return [
        field for field in _REQUIRED_PROVENANCE if not provenance.get(field)
    ]


def scientific_release_gate(artifact: dict[str, Any]) -> dict[str, Any]:
    """Validate supplied evidence, not export authenticity; missing final-
    screen evidence fails closed.
    """
    claims = artifact.get("claims") or []
    contradicted = contradicted_hypothesis_ids("", None, claim_edges=claims)
    releasable = _releasable(artifact.get("hypotheses") or [], contradicted)

    reasons = _safety_reasons(artifact.get("safety") or [])
    if not releasable:
        reasons.append("no releasable hypotheses")

    return {
        "decision": "release" if not reasons else "withhold",
        "reasons": reasons,
        "releasable_hypotheses": len(releasable),
        "contradicted_hypotheses": len(contradicted),
        "verified_claim_ratio": round(_verified_claim_ratio(claims), 4),
        "missing_provenance": _missing_provenance(
            artifact.get("provenance") or {}
        ),
    }
