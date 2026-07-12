"""Tests for evidence-derived Goal Report sections."""

from app import report_render


def _hypothesis(identifier: str, title: str) -> dict[str, object]:
    """Build one report-ready hypothesis fixture."""
    return {
        "id": identifier,
        "title": title,
        "statement": f"{title} changes the measured phenotype.",
        "mechanism": f"{title} acts through a causal feedback mechanism.",
        "experimental_context": f"Perturb {title} with matched controls.",
        "safety_status": "allowed",
    }


def test_goal_report_sections_preserve_claim_grounding() -> None:
    """Topics, insights, and idea buckets retain evidence-release decisions."""
    released = _hypothesis("h1", "Feedback control")
    rejected = _hypothesis("h2", "Unsupported bypass")
    edges = [
        {
            "hypothesis_id": "h1",
            "evidence_id": "ev1",
            "label": "supports",
        },
        {
            "hypothesis_id": "h2",
            "claim_text": "The bypass is constitutively active.",
            "label": "contradicts",
        },
    ]

    topics = report_render._knowledge_base_topics([released], edges)
    insights = report_render._agent_insights(
        [released],
        edges,
        {"common_weaknesses": ["Cell-type specificity remains uncertain."]},
    )
    buckets = report_render._idea_buckets(
        [released], [released, rejected], edges
    )

    assert topics[0]["title"] == "Feedback control"
    assert topics[0]["reference_ids"] == ["ev1"]
    assert insights["contradictions"] == [
        "The bypass is constitutively active."
    ]
    assert insights["uncertainties"] == [
        "Cell-type specificity remains uncertain."
    ]
    assert buckets["high_potential"][0]["id"] == "h1"
    assert buckets["non_viable"][0]["id"] == "h2"
    assert "Evidence verification" in buckets["non_viable"][0]["reason"]
