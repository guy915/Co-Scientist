"""The Goal Report release gate: which ideas the report may publish.

Holds the exclusion filters that decide which hypotheses reach the final
report: the contradicted/unverified id sets and the safety gate that drops
prohibited, rejected, or contradicted ideas. Two predicates are public
because callers outside the report apply them: ``exclude_unsafe_hypotheses``
(public share links) and ``unverified_hypothesis_ids`` (the run's hypotheses
endpoint).
"""

from __future__ import annotations

import logging
from typing import Any

from app import store
from app.claim_verdict import is_categorical_contradiction, is_supporting
from app.hypothesis_safety import (
    is_blocking_status,
    review_hypothesis_safety,
)
from app.hypothesis_screening import record_hypothesis_block

logger = logging.getLogger(__name__)

# Hypothesis statuses that keep an idea out of the ranked report. Everything
# else -- including ideas the initial review flagged as needing revision --
# ranks and publishes.
EXCLUDED_HYPOTHESIS_STATUSES = frozenset({"rejected", "duplicate"})


def _contradicted_hypothesis_ids(
    run_id: str,
    db_path: str | None,
    claim_edges: list[dict[str, Any]] | None = None,
) -> set[str]:
    """Ids of hypotheses with a *categorical* claim the evidence contradicts.

    An idea whose established-fact claims have evidence against them is
    withheld from the report entirely -- unlike merely-unsupported ideas,
    which are published with an "Unverified" badge.

    Speculative claims are exempt, matching ``publication_gate``: a
    contradicted *proposal* is a verdict on the idea rather than a reason to
    hide it, and the two must agree or an idea the gate ranked would still
    vanish here. Its contradicting spans stay on the claim edge, so the
    report shows the contradiction beside the idea.

    ``claim_edges`` may be passed to reuse an already-fetched edge list;
    when omitted it is queried from the store.
    """
    edges = (
        claim_edges
        if claim_edges is not None
        else store.list_claim_evidence(run_id, db_path=db_path)
    )
    return {
        str(edge["hypothesis_id"])
        for edge in edges
        if is_categorical_contradiction(edge)
    }


def _supported_hypothesis_ids(edges: list[dict[str, Any]]) -> set[str]:
    """Ids of hypotheses with at least one evidence-supported claim edge.

    The one definition of "supported" the report uses
    (:func:`app.claim_verdict.is_supporting`): a ``partial`` (near-miss)
    verdict counts alongside ``supports``, since it still means relevant,
    consistent evidence was found. Shared by
    :func:`unverified_hypothesis_ids` and :func:`_verified_hypothesis_count`
    because those two are exact complements of each other over the published
    set -- the "Unverified" badge and the "Verified ideas" tile are one fact
    shown twice, and two independently-editable copies of this rule could
    drift into contradicting each other.

    Args:
        edges: Claim-evidence edges to scan.

    Returns:
        The set of hypothesis ids carrying a supporting edge.
    """
    return {str(edge["hypothesis_id"]) for edge in edges if is_supporting(edge)}


def unverified_hypothesis_ids(
    run_id: str,
    db_path: str | None,
    hyps: list[dict[str, Any]] | None = None,
) -> set[str]:
    """Ids of published hypotheses that lack an evidence-supported claim.

    A hypothesis is "verified" once at least one of its claims has a
    ``supports`` or ``partial`` evidence edge -- a partial (near-miss) verdict
    still means relevant, consistent evidence was found, so it clears the
    badge. Under the rank-and-publish policy the rest are still ranked and
    published, but flagged "Unverified" in the report and the idea list rather
    than blocking the run.

    When a run has no claim-evidence edges at all -- claim grounding never
    ran -- none of its ideas were assessed, so none is reported unverified
    (the badge means "assessed and unsupported", not "not yet assessed").

    ``hyps`` may be passed to reuse an already-fetched hypothesis list;
    when omitted it is queried from the store.
    """
    edges = store.list_claim_evidence(run_id, db_path=db_path)
    if not edges:
        return set()
    supported = _supported_hypothesis_ids(edges)
    rows = (
        hyps
        if hyps is not None
        else store.list_hypotheses(run_id, db_path=db_path)
    )
    all_hypothesis_ids = {str(hypothesis.get("id")) for hypothesis in rows}
    return all_hypothesis_ids - supported


def _verified_hypothesis_count(
    hyps: list[dict[str, Any]],
    claim_edges: list[dict[str, Any]],
) -> int:
    """How many of the published ideas carry an evidence-supported claim.

    The exact complement of :func:`unverified_hypothesis_ids` over the
    published set, and deliberately derived from the same ``supports``/
    ``partial`` rule: the report's "Verified ideas" tile and the per-idea
    "Unverified" badge are the same fact shown twice, so they must not be
    computed two ways. The tile used to be handed the *high potential*
    count instead, which made it a duplicate of the tile beside it and let
    a run report two verified ideas while badging every idea unverified.

    A run with no claim edges at all was never assessed, so nothing is
    badged unverified and, symmetrically, nothing counts as verified.
    """
    if not claim_edges:
        return 0
    supported = _supported_hypothesis_ids(claim_edges)
    return sum(1 for hyp in hyps if str(hyp.get("id")) in supported)


def exclude_unsafe_hypotheses(
    run_id: str,
    hyps: list[dict[str, Any]],
    db_path: str | None,
    claim_edges: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Drop hypotheses a safety review or the publication gate blocks.

    Milestone 5/6/M9 wiring: a hypothesis whose safety review is prohibited/
    ethical/uncertain (SSR §1, §10) or whose claims are contradicted by the
    evidence (the publication gate, SSR §7) must not appear in the final
    report's leaderboard or top ideas. The pre-tournament screen and claim
    grounding already persisted each hypothesis's ``safety_status`` and
    claim-evidence graph and recorded their audit rows, so the common path just
    honors those. A legacy row with no persisted safety status (older runs) is
    re-reviewed and audited here as a fallback. Benign hypotheses pass through
    unchanged.

    Args:
        run_id: The run whose report is being built.
        hyps: The run's hypotheses (store rows with a ``statement`` and,
            normally, a persisted ``safety_status``).
        db_path: Optional override for the SQLite database path.
        claim_edges: Pre-fetched claim-evidence edges to reuse; queried from
            the store when omitted.

    Returns:
        The hypotheses safe to synthesize, in the original order.
    """
    contradicted = _contradicted_hypothesis_ids(run_id, db_path, claim_edges)
    kept = [
        hyp
        for hyp in hyps
        if _hypothesis_passes_safety_gate(run_id, hyp, contradicted, db_path)
    ]
    _log_gate_outcome(kept, hyps, contradicted)
    return kept


def _log_gate_outcome(
    kept: list[dict[str, Any]],
    hyps: list[dict[str, Any]],
    contradicted: set[str],
) -> None:
    """Reports, in one line, what the gate withheld from the report.

    The per-hypothesis exclusions above log at info because withholding a
    contradicted or unsafe idea is the gate working as designed: a warning
    per idea puts a row that needs no action into the warnings band, once
    per excluded idea, and buries the run's narrative under them. The one
    outcome that does need attention is the gate taking everything, which
    leaves a report with no ideas in it -- and since that is an operator's
    first stop, it carries the same cause breakdown as the reader-facing
    blocked reason (:func:`_empty_leaderboard_reason`), built from data
    already in hand here rather than a fixed guess at what went wrong.

    Args:
        kept: The hypotheses that cleared the gate.
        hyps: Every hypothesis offered to it.
        contradicted: Ids with a claim the evidence contradicts, as
            computed by the caller.
    """
    total = len(hyps)
    if total and not kept:
        tally = _exclusion_tally(hyps, kept, contradicted)
        logger.warning(
            "Report gate: excluded all %s hypotheses from synthesis (%s); "
            "the report has no ideas to show.",
            total,
            _join_clauses(_exclusion_clauses(tally)),
        )
        return
    if len(kept) < total:
        logger.info(
            "Report gate: excluded %s of %s hypotheses from synthesis.",
            total - len(kept),
            total,
        )


# One cause per excluded hypothesis, in the order a summary sentence lists
# them. Order mirrors where each check sits in _hypothesis_passes_safety_gate
# (status first, then a contradicting claim, then a blocking safety status),
# so a mixed run reads causes in the same order the gate applied them.
_EXCLUSION_CAUSE_ORDER = (
    "review_rejected",
    "duplicate",
    "contradicted",
    "safety",
)

# Distinct wording per cause -- the documented rule that "duplicate" and
# "rejected" (and, here, a safety-review hold) must reach the reader as
# different words rather than one shared sentence. "unsafe" is named as the
# *reviewer's own* judgment, not the separate safety-review pipeline, so a
# sentence naming both causes in a mixed run does not read as saying the
# same thing twice.
_EXCLUSION_CAUSE_PHRASES = {
    "review_rejected": (
        "rejected by peer review before ranking (the reviewer judged them "
        "inaccurate, non-novel, unsafe, or evidence-blocked)"
    ),
    "duplicate": "folded into a higher-ranked idea that says the same thing",
    "contradicted": "contradicted by the evidence",
    "safety": "withheld by the safety review",
}


def _exclusion_cause(hyp: dict[str, Any], contradicted: set[str]) -> str:
    """Classify why one already-excluded hypothesis left the ranked report.

    Mirrors ``_hypothesis_passes_safety_gate``'s own precedence exactly
    (status, then a contradicting claim, then a blocking safety status), so
    a summary built from this never disagrees with which ideas the gate
    actually excluded. Only meaningful for a hypothesis the gate has
    already dropped -- every excluded hypothesis matches one of these
    branches by construction, so the safety fallback at the end is reached
    only by the gate's own legacy re-review path.
    """
    status = hyp.get("status")
    if status == "duplicate":
        return "duplicate"
    if status == "rejected":
        return "review_rejected"
    if str(hyp.get("id")) in contradicted:
        return "contradicted"
    return "safety"


def _exclusion_tally(
    hyps: list[dict[str, Any]],
    kept: list[dict[str, Any]],
    contradicted: set[str],
) -> dict[str, int]:
    """Count why each excluded hypothesis left the ranked report."""
    kept_ids = {str(hyp.get("id")) for hyp in kept}
    tally = dict.fromkeys(_EXCLUSION_CAUSE_ORDER, 0)
    for hyp in hyps:
        if str(hyp.get("id")) in kept_ids:
            continue
        tally[_exclusion_cause(hyp, contradicted)] += 1
    return tally


def _exclusion_clauses(tally: dict[str, int]) -> list[str]:
    """Render each nonzero cause in ``tally`` as one counted clause."""
    clauses = []
    for cause in _EXCLUSION_CAUSE_ORDER:
        count = tally.get(cause, 0)
        if not count:
            continue
        verb = "was" if count == 1 else "were"
        clauses.append(f"{count} {verb} {_EXCLUSION_CAUSE_PHRASES[cause]}")
    return clauses


def _join_clauses(clauses: list[str]) -> str:
    """Join clauses with commas and a trailing 'and', English-list style."""
    if len(clauses) <= 1:
        return clauses[0] if clauses else ""
    if len(clauses) == 2:
        return " and ".join(clauses)
    return ", ".join(clauses[:-1]) + ", and " + clauses[-1]


def _empty_leaderboard_reason(idea_count: int, tally: dict[str, int]) -> str:
    """One sentence naming why an empty leaderboard blocked the run.

    Derived from the actual per-hypothesis exclusion causes rather than a
    fixed pair of guesses: a run whose ideas were all rejected by peer
    review before any evidence or safety pass ever ran used to be told
    "contradicted by the evidence or withheld by the safety review" --
    both false, since neither pipeline had touched a single idea. A mix of
    causes lists every one that applied, each in its own words.

    Args:
        idea_count: Every idea the run produced (``payload["idea_count"]``;
            the leaderboard is empty only when none of them passed the
            gate). Zero is its own case: nothing was withheld because
            nothing was ever generated.
        tally: This run's exclusion counts, from :func:`_exclusion_tally`.

    Returns:
        The reader-facing blocked-run reason, one sentence.
    """
    if not idea_count:
        return "No hypothesis could be published: the run produced no ideas."
    clauses = _exclusion_clauses(tally)
    if not clauses:
        return (
            "No hypothesis could be published: every idea was withheld "
            "from the ranked report."
        )
    total = sum(tally.values())
    noun = "idea" if total == 1 else "ideas"
    return (
        f"No hypothesis could be published: of {total} {noun}, "
        f"{_join_clauses(clauses)}."
    )


def _hypothesis_passes_safety_gate(
    run_id: str,
    hyp: dict[str, Any],
    contradicted: set[str],
    db_path: str | None,
) -> bool:
    """Return whether one hypothesis clears the contradiction/safety gate."""
    # "duplicate" is excluded for the same reason as "rejected" (it is
    # redundant with a higher-ranked idea) but for a different reason than
    # "rejected" means; see _non_viable_reasons, which reports them apart.
    if hyp.get("status") in EXCLUDED_HYPOTHESIS_STATUSES:
        return False
    # Contradicted ideas have evidence against them and are withheld
    # entirely; merely-unsupported ideas are published with an "Unverified"
    # badge (see unverified_hypothesis_ids), not excluded here.
    if str(hyp.get("id")) in contradicted:
        logger.info(
            "Excluding hypothesis %s from synthesis: contradicted claim",
            hyp.get("id"),
        )
        return False
    status = hyp.get("safety_status")
    # Common path: the screen already decided; honor the persisted status
    # without re-reviewing or double-recording the audit row.
    if status and status != "pending":
        if is_blocking_status(str(status)):
            logger.info(
                "Excluding hypothesis %s from synthesis: %s",
                hyp.get("id"),
                status,
            )
            return False
        return True
    return _legacy_hypothesis_passes_safety_gate(run_id, hyp, db_path)


def _legacy_hypothesis_passes_safety_gate(
    run_id: str, hyp: dict[str, Any], db_path: str | None
) -> bool:
    """Re-review and audit a row the pre-tournament screen never touched."""
    review = review_hypothesis_safety(str(hyp.get("statement") or ""))
    if not review.blocks_tournament:
        return True
    record_hypothesis_block(run_id, hyp.get("id"), review, db_path=db_path)
    logger.info(
        "Excluding hypothesis %s from synthesis: %s",
        hyp.get("id"),
        review.outcome.value,
    )
    return False
