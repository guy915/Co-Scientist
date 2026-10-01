"""The Goal Report's contradictions panel must not misstate what was withheld.

Split from ``test_goal_report_sections.py``, which is at the module-size
budget. The panel lists every contradicted claim; what it says about the
claim's idea has to agree with the release gate.
"""

from typing import Any

from app.report import content as report_content
from app.report import gates as report_gates


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
