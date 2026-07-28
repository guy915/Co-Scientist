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


def _edge(
    hypothesis_id: str,
    claim: str,
    label: str,
    evidence_ids: tuple[str, ...] = (),
) -> dict[str, object]:
    """Build one edge in the shape ``store.list_claim_evidence`` returns.

    The column names matter: the report derives contradiction text from
    ``claim`` and evidence ids from the ``supporting`` passage spans, so a
    fixture inventing flatter keys hides real key drift.
    """
    return {
        "hypothesis_id": hypothesis_id,
        "claim": claim,
        "label": label,
        "claim_role": "categorical",
        "supporting": [
            {"evidence_id": evidence_id, "quote": "A cited passage."}
            for evidence_id in evidence_ids
        ],
        "contradicting": [],
        "assessor": "llm",
    }


def test_goal_report_sections_preserve_claim_grounding() -> None:
    """Topics, insights, and idea buckets retain evidence-release decisions."""
    released = _hypothesis("h1", "Feedback control")
    rejected = _hypothesis("h2", "Unsupported bypass")
    edges = [
        _edge("h1", "Feedback is rate-limiting.", "supports", ("ev1",)),
        _edge("h2", "The bypass is constitutively active.", "contradicts"),
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


def test_idea_buckets_partition_every_idea() -> None:
    """The two buckets cover the run's ideas exactly once, at any size.

    The UI shows both as counts side by side, so they have to sum to the
    run's idea count. ``non_viable`` is defined as everything not released,
    and ``high_potential`` used to be capped at the top five -- which held
    only until a run released a sixth idea, then quietly lost the rest.
    """
    released = [_hypothesis(f"h{i}", f"Released {i}") for i in range(7)]
    excluded = [_hypothesis("x1", "Excluded")]

    buckets = report_render._idea_buckets(released, released + excluded, [])

    assert len(buckets["high_potential"]) == 7
    assert len(buckets["non_viable"]) == 1
    assert {entry["id"] for entry in buckets["high_potential"]} | {
        entry["id"] for entry in buckets["non_viable"]
    } == {hyp["id"] for hyp in released + excluded}


def test_idea_buckets_explain_a_review_rejected_idea_as_deduplicated() -> None:
    """A review/dedup-rejected idea gets an accurate reason, not "release gate".

    Under rank-and-publish a merely-unsupported idea is published (badged
    "Unverified"), so the only non-viable ideas are contradicted, unsafe, or
    set aside during review/deduplication. A rejected idea with no contradicting
    edge must be explained by that rejection -- never the legacy "release gate
    excluded this idea" text.
    """
    released = _hypothesis("h1", "Feedback control")
    deduped = _hypothesis("h2", "Near-duplicate idea")
    deduped["status"] = "rejected"
    # A speculative/insufficient edge is not a publication blocker, so it yields
    # no exclusion reason -- the rejection must be explained by the status.
    edges = [_edge("h2", "A speculative claim.", "insufficient", ("ev1",))]
    edges[0]["claim_role"] = "speculative"
    buckets = report_render._idea_buckets(
        [released], [released, deduped], edges
    )
    reason = buckets["non_viable"][0]["reason"].lower()
    assert "review" in reason or "duplicate" in reason
    assert "release gate" not in reason


def test_a_duplicate_and_a_rejected_idea_get_different_reasons() -> None:
    """Deduplication and review rejection are different facts, reported apart.

    Both leave the ranked report, but a duplicate was never judged -- a
    higher-ranked idea simply says the same thing. One shared sentence told
    a scientist their idea had failed peer review when it had only been
    folded into another.
    """
    released = _hypothesis("h1", "Feedback control")
    deduped = _hypothesis("h2", "Near-duplicate idea")
    deduped["status"] = "duplicate"
    rejected = _hypothesis("h3", "Unsound idea")
    rejected["status"] = "rejected"

    buckets = report_render._idea_buckets(
        [released], [released, deduped, rejected], []
    )

    reasons = {entry["id"]: entry["reason"] for entry in buckets["non_viable"]}
    assert "higher-ranked" in reasons["h2"]
    assert "review" in reasons["h3"].lower()
    assert reasons["h2"] != reasons["h3"]


def test_contradictions_carry_claim_text_and_never_blank_entries() -> None:
    """Every contradiction is readable text, so no empty bullet is emitted.

    A blank entry is worse than an absent one: the section header renders on
    list length alone, so blanks produce a heading with nothing under it.
    """
    hypothesis = _hypothesis("h1", "Feedback control")
    edges = [
        _edge("h1", "The bypass is constitutively active.", "contradicts"),
        _edge("h1", "", "contradicts"),
        _edge("h1", "Feedback is rate-limiting.", "supports"),
    ]

    insights = report_render._agent_insights([hypothesis], edges, {})

    assert insights["contradictions"] == [
        "The bypass is constitutively active."
    ]


def test_recommended_directions_keep_their_three_named_fields() -> None:
    """Structured recommendations survive as fields, not stringified objects."""
    meta = {
        "strategic_recommendations": [
            {
                "focus_area": "Receptor pharmacology",
                "recommendation": "Measure binding directly.",
                "justification": "The affinity is unproven.",
            },
            "A bare string recommendation.",
        ]
    }

    insights = report_render._agent_insights([], [], meta)

    assert insights["recommended_directions"] == [
        {
            "focus_area": "Receptor pharmacology",
            "recommendation": "Measure binding directly.",
            "justification": "The affinity is unproven.",
        },
        {
            "focus_area": "",
            "recommendation": "A bare string recommendation.",
            "justification": "",
        },
    ]


def test_synthesized_topics_map_only_to_persisted_evidence() -> None:
    """Engine topic references become ids; unsupported topics drop."""
    overview = {
        "knowledge_base": [
            {
                "id": "topic-1",
                "title": "Cross-source mechanism",
                "summary": "Two findings converge.",
                "detail": "A detailed synthesis.",
                "uncertainty": "The causal direction remains uncertain.",
                "references": [
                    {"title": "Persisted study"},
                    {"title": "Missing study"},
                ],
            },
            {
                "id": "topic-2",
                "title": "Unsupported synthesis",
                "references": [{"title": "Missing study"}],
            },
        ]
    }
    topics = report_render._synthesized_knowledge_base_topics(
        overview, [{"id": "ev-1", "title": "Persisted study"}]
    )

    assert len(topics) == 1
    assert topics[0]["reference_ids"] == ["ev-1"]
    assert topics[0]["uncertainty"].startswith("The causal direction")
