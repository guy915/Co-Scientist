"""Tests for the empty-leaderboard blocked-run reason.

Split out of ``test_goal_report_sections.py`` when that file passed the
module-size budget. ``_empty_leaderboard_reason`` is the one place that
turns a tally of why every idea left the report into the sentence a
scientist reads, so its wording -- which cause it names, which it omits,
how it reads a mix of causes -- gets its own module rather than sharing one
with the rest of the report-section tests.
"""

from typing import Any

from app.report import content as report_content
from app.report import gates as report_gates


def test_empty_leaderboard_reason_names_review_rejection_alone() -> None:
    """A run every idea failed peer review must not blame safety/evidence.

    Reproduces run 44e848fb: safety screened 18/blocked 0, claim grounding
    assessed 0 claims, and every idea carried a blocking review
    disposition. The old fixed-pair reason ("contradicted by the evidence
    or withheld by the safety review") named two causes that never ran.
    """
    tally = {
        "review_rejected": 15,
        "duplicate": 0,
        "contradicted": 0,
        "safety": 0,
    }

    reason = report_gates._empty_leaderboard_reason(15, tally)

    assert reason == (
        "No hypothesis could be published: of 15 ideas, 15 were rejected "
        "by peer review before ranking (the reviewer judged them "
        "inaccurate, non-novel, unsafe, or evidence-blocked)."
    )
    assert "safety review" not in reason
    assert "contradicted" not in reason


def test_empty_leaderboard_reason_keeps_safety_wording() -> None:
    """A genuinely safety-withheld run still says so."""
    tally = {
        "review_rejected": 0,
        "duplicate": 0,
        "contradicted": 0,
        "safety": 5,
    }

    reason = report_gates._empty_leaderboard_reason(5, tally)

    assert reason == (
        "No hypothesis could be published: of 5 ideas, 5 were withheld "
        "by the safety review."
    )
    assert "peer review" not in reason
    assert "contradicted" not in reason


def test_empty_leaderboard_reason_keeps_evidence_wording() -> None:
    """A genuinely evidence-contradicted run still says so."""
    tally = {
        "review_rejected": 0,
        "duplicate": 0,
        "contradicted": 3,
        "safety": 0,
    }

    reason = report_gates._empty_leaderboard_reason(3, tally)

    assert reason == (
        "No hypothesis could be published: of 3 ideas, 3 were "
        "contradicted by the evidence."
    )
    assert "peer review" not in reason
    assert "safety review" not in reason


def test_empty_leaderboard_reason_names_duplicates_distinctly() -> None:
    """Duplicate exclusion reads as its own cause, not "rejected"."""
    tally = {
        "review_rejected": 0,
        "duplicate": 2,
        "contradicted": 0,
        "safety": 0,
    }

    reason = report_gates._empty_leaderboard_reason(2, tally)

    assert "folded into a higher-ranked idea" in reason
    assert "peer review" not in reason
    assert "rejected" not in reason


def test_empty_leaderboard_reason_reads_a_mix_as_a_mix() -> None:
    """Several causes each land as their own clause, not one picked cause."""
    tally = {
        "review_rejected": 2,
        "duplicate": 0,
        "contradicted": 1,
        "safety": 1,
    }

    reason = report_gates._empty_leaderboard_reason(4, tally)

    assert "2 were rejected by peer review" in reason
    assert "1 was contradicted by the evidence" in reason
    assert "1 was withheld by the safety review" in reason
    assert reason.count(",") >= 2  # more than one clause is actually listed


def test_empty_leaderboard_reason_handles_zero_ideas() -> None:
    """A run that produced no ideas at all is its own case, not "withheld"."""
    reason = report_gates._empty_leaderboard_reason(
        0,
        {"review_rejected": 0, "duplicate": 0, "contradicted": 0, "safety": 0},
    )

    assert (
        reason == "No hypothesis could be published: the run produced no ideas."
    )


def _hypothesis(identifier: str, title: str) -> dict[str, object]:
    """One report-ready hypothesis the safety review has already allowed."""
    return {
        "id": identifier,
        "title": title,
        "statement": f"{title} changes the measured phenotype.",
        "safety_status": "allowed",
    }


def _contradicted(hypothesis_id: str, claim: str, role: str) -> dict[str, Any]:
    """A contradicted edge as ``store.list_claim_evidence`` returns it."""
    return {
        "hypothesis_id": hypothesis_id,
        "claim": claim,
        "label": "contradicts",
        "claim_role": role,
        "supporting": [],
        "contradicting": [{"evidence_id": "ev1", "quote": "A cited passage."}],
        "assessor": "llm",
    }


def test_a_contradicted_proposal_is_not_reported_as_withheld() -> None:
    """The panel only says "withheld" of an idea the gate actually withheld.

    The gate withholds an idea for a contradicted *categorical* claim; one
    contradicting only the idea's own proposal publishes with the idea. The
    panel lists both (the evidence against a proposal is a finding), but its
    entry used to say the idea was withheld for either, which is false of the
    proposal's idea: that idea is in the report the entry sits in.
    """
    withheld = _hypothesis("h2", "Unsupported bypass")
    proposing = _hypothesis("h3", "Speculative bypass")
    edges = [
        _contradicted(
            "h2", "The bypass is constitutively active.", "categorical"
        ),
        _contradicted(
            "h3", "Blocking the loop may raise the flux.", "speculative"
        ),
    ]

    published = report_gates.exclude_unsafe_hypotheses(
        "run-1", [withheld, proposing], None, edges
    )
    insights = report_content._agent_insights(published, edges, {})

    assert [hyp["id"] for hyp in published] == ["h3"]
    by_claim = {
        entry.split(" (", 1)[0]: entry for entry in insights["contradictions"]
    }
    assert "withheld" in by_claim["The bypass is constitutively active."]
    assert "withheld" not in by_claim["Blocking the loop may raise the flux."]
