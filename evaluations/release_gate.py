"""Scientific release gate over a completed run artifact.

**This gate applies the rules the app actually publishes by.** It used to
apply its own, which is the defect recorded as ``L1``: an evaluator that
invents thresholds proves only that the evaluator is self-consistent, and
a green run of it said nothing about whether live finalization withholds
anything. Every predicate below is imported from the modules the live
finalize path calls (``app.report_content_gates``,
``app.hypothesis_safety``), so a change to publication behavior either
shows up here or is not a change to publication behavior.

The live rules, in the order finalization applies them
(``app.report_render._finalize_report_pipeline``):

1. The final report-level safety screen withholds the whole report on a
   ``block`` or a ``hold``. An unresolved safety review is the artifact
   form of that.
2. Each hypothesis is dropped if it was rejected or deduplicated, if the
   evidence *contradicts* it, or if its safety status blocks.
3. If nothing survives, the report is withheld for an empty leaderboard.

Two rules this file used to enforce are deliberately **not** gates, and
are reported as observations instead:

- **Verified-claim ratio.** Production publishes an unsupported (but
  uncontradicted) idea with an explicit "Unverified" badge rather than
  withholding it -- see ``_unverified_hypothesis_ids``. A gate demanding
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

from app.hypothesis_safety import is_blocking_status
from app.report_content_gates import (
    EXCLUDED_HYPOTHESIS_STATUSES,
    _contradicted_hypothesis_ids,
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
        and not is_blocking_status(str(hyp.get("safety_status") or ""))
    ]


def _safety_reasons(safety: list[dict[str, Any]]) -> list[str]:
    """Flags an unresolved safety review, if any.

    The artifact form of the live report-level gate, which withholds on a
    ``block`` or a ``hold`` -- a review still requiring adjudication is a
    hold that nobody has cleared.
    """
    if any(
        item.get("requires_review") and not item.get("resolution")
        for item in safety
    ):
        return ["unresolved safety review"]
    return []


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
            edges, and provenance.

    Returns:
        The decision, the reasons behind it, and the observations that are
        reported rather than enforced.
    """
    claims = artifact.get("claims") or []
    contradicted = _contradicted_hypothesis_ids("", None, claim_edges=claims)
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
