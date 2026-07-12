"""Scientific release gate over a completed run artifact."""

from __future__ import annotations

from typing import Any


def scientific_release_gate(
    artifact: dict[str, Any], *, minimum_verified_ratio: float = 0.8
) -> dict[str, Any]:
    """Return a fail-closed publication decision with explicit reasons."""
    reasons: list[str] = []
    hypotheses = artifact.get("hypotheses") or []
    if not hypotheses:
        reasons.append("no releasable hypotheses")
    safety = artifact.get("safety") or []
    if any(
        item.get("requires_review") and not item.get("resolution")
        for item in safety
    ):
        reasons.append("unresolved safety review")
    claims = artifact.get("claims") or []
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
    provenance = artifact.get("provenance") or {}
    for field in ("model", "policy_version", "retrieval_sources"):
        if not provenance.get(field):
            reasons.append(f"missing provenance: {field}")
    return {
        "decision": "release" if not reasons else "withhold",
        "reasons": reasons,
        "verified_claim_ratio": round(ratio, 4),
        "minimum_verified_ratio": minimum_verified_ratio,
    }
