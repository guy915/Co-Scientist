"""Pre-ranking evidence-gate eligibility tests for the durable executor.

Covers the rank-and-publish policy: an unsupported (but non-contradicted) idea
stays rankable, its claim graduates to supported once evidence arrives, and a
claim-gated idea is left out of the decisive Elo tournament. Split from
``test_engine_tasks.py`` to keep that core file small.
"""

from typing import Any

import pytest
from co_scientist.models import (
    Article,
    Hypothesis,
)

from app import engine_tasks


@pytest.mark.asyncio
async def test_pre_ranking_gate_keeps_unsupported_ideas_rankable() -> None:
    """Unsupported (but non-contradicted) ideas stay rankable.

    Under the rank-and-publish policy the pre-ranking gate only withholds
    contradicted or unsafe ideas; a merely-unsupported idea stays viable (it is
    later published and badged "unverified") rather than being quarantined.
    """
    supported = Hypothesis(
        text="Astrocyte lactate accelerates synaptic ATP recovery."
    )
    unsupported = Hypothesis(
        text="We hypothesize a fictional kinase may alter neuronal aging.",
        literature_grounding=(
            "A fictional kinase completely reverses neuronal aging."
        ),
    )
    for hypothesis in (supported, unsupported):
        hypothesis.review_disposition = "viable"
    state = {
        "hypotheses": [supported, unsupported],
        "articles": [
            Article(
                title="Astrocyte energetics",
                abstract=(
                    "Astrocyte lactate accelerates synaptic ATP recovery."
                ),
                source_id="PMID-1",
            )
        ],
    }

    await engine_tasks._apply_pre_ranking_evidence_gate(state)

    assert supported.review_disposition == "viable"
    assert supported.enrichments["claim_gate"]["decision"] == "allow"
    assert unsupported.review_disposition == "viable"
    assert unsupported.enrichments["claim_gate"]["decision"] == "allow"


@pytest.mark.asyncio
async def test_pre_ranking_gate_records_support_when_evidence_arrives() -> None:
    """A rankable idea's claim graduates to supported once evidence arrives."""
    hypothesis = Hypothesis(
        text="Astrocyte lactate accelerates synaptic ATP recovery.",
        literature_grounding=(
            "Astrocyte lactate accelerates synaptic ATP recovery."
        ),
    )
    hypothesis.review_disposition = "viable"
    state: dict[str, Any] = {"hypotheses": [hypothesis], "articles": []}
    await engine_tasks._apply_pre_ranking_evidence_gate(state)
    # No evidence yet, but a merely-unsupported idea still ranks.
    assert hypothesis.review_disposition == "viable"

    state["articles"] = [
        Article(
            title="Synaptic energetics",
            abstract="Astrocyte lactate accelerates synaptic ATP recovery.",
        )
    ]
    await engine_tasks._apply_pre_ranking_evidence_gate(state)

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.enrichments["claim_gate"]["decision"] == "allow"


def test_evidence_blocked_idea_is_excluded_from_ranking() -> None:
    """A claim-gated idea must not enter the decisive Elo tournament.

    The pre-ranking gate marks an unsupported idea ``evidence_blocked``; the
    ranking scheduler must then leave it out of the tournament, not merely drop
    it at publish time, so its unsupported claim never shifts other ideas' Elo.
    """
    supported = Hypothesis(text="Supported idea.")
    supported.review_disposition = "viable"
    blocked = Hypothesis(text="Unsupported idea.")
    blocked.review_disposition = "evidence_blocked"
    # Deep verification is the other way round: its verdict demotes rather
    # than withholds, so an undermined idea keeps competing. The durable
    # path must agree with the engine's own predicate about that, which is
    # why it asks ``Hypothesis.is_rankable`` instead of restating the rule.
    undermined = Hypothesis(text="Undermined idea.")
    undermined.review_disposition = "viable"
    undermined.deep_verification_verdict = "undermined"

    eligible = engine_tasks._ranking_eligible(
        {"hypotheses": [supported, blocked, undermined]}
    )

    assert supported in eligible
    assert blocked not in eligible
    assert undermined in eligible
