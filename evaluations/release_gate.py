"""Scientific release gate over a completed run artifact.

Publication decisions reuse the live predicates in ``app.report.gates``
and ``app.hypothesis.safety``. Artifact admission is deliberately stricter:
missing final-screen evidence or a statement needed to reconstruct a legacy
hypothesis decision prevents this evaluator from proving publication readiness.
Those completeness prerequisites are not additional live publication rules.

The publication checks and artifact prerequisites, in finalization order
(``app.report.finalize._finalize_report_pipeline``):

1. The final report-level safety screen withholds the whole report on a
   ``block`` or a ``hold``. The latest final-stage audit record is required;
   absence of an unresolved review is not evidence that screening occurred.
2. Each hypothesis is dropped if it was rejected or deduplicated, if the
   evidence *contradicts* it, or if its safety status blocks.
3. If nothing survives, the report is withheld for an empty leaderboard.

Two rules this file used to enforce are deliberately **not** gates, and
are reported as observations instead:

- **Verified-claim ratio.** Production publishes an unsupported (but
  uncontradicted) idea with an explicit "Unverified" badge rather than
  withholding it -- see ``unverified_hypothesis_ids``. A gate demanding
  80% supported claims would withhold essentially every real run, and
  asserting it here while production does the opposite is exactly the
  divergence ``L1`` is about. The ratio is still computed and returned,
  because it is the number a reader should judge a report by.
- **Provenance completeness.** Worth reporting, never a reason to
  withhold science; nothing in the live path treats it as one.
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
    """Apply the live per-hypothesis publication gate."""
    return [
        hyp
        for hyp in hypotheses
        if hyp.get("status") not in EXCLUDED_HYPOTHESIS_STATUSES
        and str(hyp.get("id")) not in contradicted
        and _passes_hypothesis_safety(hyp)
    ]


def _passes_hypothesis_safety(hyp: dict[str, Any]) -> bool:
    """Reuse the live legacy classifier without its database audit writes."""
    status = hyp.get("safety_status")
    if status and status != "pending":
        return not is_blocking_status(str(status))
    statement = hyp.get("statement")
    if not isinstance(statement, str) or not statement.strip():
        return False
    return not review_hypothesis_safety(statement).blocks_tournament


def _safety_reasons(safety: list[dict[str, Any]]) -> list[str]:
    """Require the latest final screen, using public safety-record IDs.

    Approval of an old hold schedules another finalization; it does not
    change that hold into proof of a successful final screen. Hypothesis
    holds exclude individual ideas rather than the entire report.
    """
    finals = [item for item in safety if item.get("stage") == "final"]
    if not finals:
        return ["missing final safety screen"]
    if any(type(item.get("id")) is not int for item in finals):
        return ["invalid final safety record identity"]
    final = max(finals, key=lambda item: item["id"])
    return _final_safety_reasons(final)


def _final_safety_reasons(final: dict[str, Any]) -> list[str]:
    """Match the terminal decision used by live report finalization."""
    decision = final.get("decision")
    if decision == "allow":
        return []
    if decision == "redact" and final.get("matches"):
        return []
    return ["final safety screen withheld publication"]


def _verified_claim_ratio(claims: list[dict[str, Any]]) -> float:
    """Fraction of assessed claims the evidence supports. Reported only."""
    if not claims:
        return 0.0
    supported = sum(1 for claim in claims if claim.get("label") == "supports")
    return supported / len(claims)


def _missing_provenance(provenance: dict[str, Any]) -> list[str]:
    """Names each absent provenance field. Reported, never a gate reason."""
    return [
        field for field in _REQUIRED_PROVENANCE if not provenance.get(field)
    ]


def scientific_release_gate(artifact: dict[str, Any]) -> dict[str, Any]:
    """Return a fail-closed publication decision with explicit reasons.

    Args:
        artifact: A completed run's hypotheses, safety decisions, claim
            edges, and provenance. Safety records use the public API shape
            with integer IDs; hypotheses need a persisted safety status or
            their statement for the same deterministic legacy re-screen.
            This validates supplied evidence, not the authenticity of exports.

    Returns:
        The decision, the reasons behind it, and the observations that are
        reported rather than enforced.
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
