"""Scientific release gate over a completed run artifact."""

from __future__ import annotations

from typing import Any


def _safety_reasons(safety: list[dict[str, Any]]) -> list[str]:
    """Flags an unresolved safety review, if any."""
    if any(
        item.get("requires_review") and not item.get("resolution")
        for item in safety
    ):
        return ["unresolved safety review"]
    return []


def _claims_reasons(
    claims: list[dict[str, Any]], minimum_verified_ratio: float
) -> tuple[list[str], float]:
    """Flags contradicted claims and an under-threshold verified ratio.

    Args:
        claims: Per-claim entailment records.
        minimum_verified_ratio: Minimum fraction of claims that must be
            labeled "supports" for release.

    Returns:
        A (reasons, verified_claim_ratio) pair.
    """
    reasons = []
    if any(item.get("label") == "contradicts" for item in claims):
        reasons.append("contradicted scientific claim")
    assessed = len(claims)
    verified = sum(item.get("label") == "supports" for item in claims)
    ratio = verified / assessed if assessed else 0.0
    if ratio < minimum_verified_ratio:
        reasons.append(
            "verified claim ratio "
            f"{ratio:.3f} below {minimum_verified_ratio:.3f}"
        )
    return reasons, ratio


def _provenance_reasons(provenance: dict[str, Any]) -> list[str]:
    """Flags each required provenance field that is missing."""
    return [
        f"missing provenance: {field}"
        for field in ("model", "policy_version", "retrieval_sources")
        if not provenance.get(field)
    ]


def scientific_release_gate(
    artifact: dict[str, Any], *, minimum_verified_ratio: float = 0.8
) -> dict[str, Any]:
    """Return a fail-closed publication decision with explicit reasons."""
    reasons: list[str] = []
    hypotheses = artifact.get("hypotheses") or []
    if not hypotheses:
        reasons.append("no releasable hypotheses")
    reasons.extend(_safety_reasons(artifact.get("safety") or []))
    claim_reasons, ratio = _claims_reasons(
        artifact.get("claims") or [], minimum_verified_ratio
    )
    reasons.extend(claim_reasons)
    reasons.extend(_provenance_reasons(artifact.get("provenance") or {}))
    return {
        "decision": "release" if not reasons else "withhold",
        "reasons": reasons,
        "verified_claim_ratio": round(ratio, 4),
        "minimum_verified_ratio": minimum_verified_ratio,
    }
