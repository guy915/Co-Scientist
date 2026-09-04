"""The blocked-run reason and each idea's own reason must agree on why.

``_hypothesis_passes_safety_gate`` (report_content_gates.py) decides
exclusion in a fixed order: status (duplicate/rejected) first, then a
contradicting claim, then a blocking safety status. ``_exclusion_cause``
mirrors that order to build the run-level blocked reason
(``_empty_leaderboard_reason``). ``_non_viable_reasons`` (report_content.py)
builds the per-idea reason shown in ``idea_buckets`` and must mirror the
same precedence, or a hypothesis that is both status-rejected and
contradicted gets attributed to two different causes on the two surfaces:
the run's blocked reason names one cause while the per-idea reason names
another, for the very same exclusion decision.
"""

from app import report_content, report_render


def _hypothesis(identifier: str, status: str) -> dict[str, object]:
    """Build one report-ready hypothesis fixture with a given status."""
    return {
        "id": identifier,
        "title": "An idea",
        "text": "An idea that is both rejected and contradicted.",
        "status": status,
        "safety_status": "allowed",
    }


def _contradicting_edge(hypothesis_id: str) -> dict[str, object]:
    """Build one categorical 'contradicts' claim edge for a hypothesis."""
    return {
        "hypothesis_id": hypothesis_id,
        "claim": "The idea contradicts prior data.",
        "label": "contradicts",
        "claim_role": "categorical",
        "supporting": [],
        "contradicting": [],
        "assessor": "llm",
    }


def test_rejected_and_contradicted_idea_agrees_across_both_surfaces() -> None:
    """One hypothesis, two report surfaces, one cause.

    The gate excludes this idea for its status -- checked before the
    contradicting claim is ever considered (see
    ``_hypothesis_passes_safety_gate``) -- so both the run's blocked
    reason and the idea's own per-idea reason must say the idea was set
    aside during review, never that it was contradicted by the evidence.
    """
    hyp = _hypothesis("h1", "rejected")
    edges = [_contradicting_edge("h1")]

    contradicted = report_content._contradicted_hypothesis_ids(
        "run1", None, edges
    )
    assert "h1" in contradicted  # sanity: the idea really is both

    buckets = report_render._idea_buckets([], [hyp], edges)
    per_idea_reason = buckets["non_viable"][0]["reason"].lower()

    tally = report_content._exclusion_tally([hyp], [], contradicted)
    blocked_reason = report_content._empty_leaderboard_reason(1, tally).lower()

    assert "review" in per_idea_reason
    assert "contradicted" not in per_idea_reason
    assert "review" in blocked_reason
    assert "contradicted" not in blocked_reason


def test_duplicate_and_contradicted_idea_agrees_across_both_surfaces() -> None:
    """Same scenario, the other status the gate checks before evidence."""
    hyp = _hypothesis("h2", "duplicate")
    edges = [_contradicting_edge("h2")]

    contradicted = report_content._contradicted_hypothesis_ids(
        "run1", None, edges
    )
    assert "h2" in contradicted  # sanity: the idea really is both

    buckets = report_render._idea_buckets([], [hyp], edges)
    per_idea_reason = buckets["non_viable"][0]["reason"].lower()

    tally = report_content._exclusion_tally([hyp], [], contradicted)
    blocked_reason = report_content._empty_leaderboard_reason(1, tally).lower()

    assert "higher-ranked" in per_idea_reason
    assert "contradicted" not in per_idea_reason
    assert "folded into a higher-ranked idea" in blocked_reason
    assert "contradicted" not in blocked_reason
