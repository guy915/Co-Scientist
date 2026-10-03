"""Tests for ``co_scientist.agents.evolution.evolve_context``.

Covers ``_specialist_feedback_for``, the per-hypothesis evidence ledger
(debate slices, tournament outcomes, proximity neighbors, and deep-
verification notes) threaded into each evolution prompt.
"""

import json

from co_scientist.agents.evolution.evolve_context import (
    _specialist_feedback_for,
)
from co_scientist.models import Hypothesis
from co_scientist.state import WorkflowState
from tests._state import make_hypothesis, make_state


def _feedback_state(hypothesis: Hypothesis) -> WorkflowState:
    """Build a state carrying debate, tournament, and proximity feedback."""
    return make_state(
        hypotheses=[hypothesis],
        debate_transcripts=[
            {
                "debate_id": 3,
                "hypothesis_text": hypothesis.text,
                "transcript": "Skeptic requests a rescue experiment.",
            }
        ],
        tournament_matchups=[
            {
                "hypothesis_a_id": hypothesis.id,
                "hypothesis_b_id": "peer",
                "winner_id": "peer",
                "reasoning": "The peer has stronger causal controls.",
                "confidence": "high",
            }
        ],
        proximity_graph={
            "edges": [
                {
                    "source": hypothesis.id,
                    "target": "neighbor",
                    "similarity": 0.72,
                    "cluster_id": "c1",
                }
            ]
        },
    )


def test_specialist_feedback_joins_prior_agent_outputs() -> None:
    """Evolution receives debate, tournament, proximity, and probe feedback."""
    hypothesis = make_hypothesis(
        text="mitochondrial checkpoint controls neuronal aging",
        deep_verification_verdict="partially_holds",
        deep_verification_probes=[
            {"question": "Is it causal?", "answer": "Unknown"}
        ],
    )
    hypothesis.enrichments["claim_gate"] = {
        "decision": "block",
        "reason": "one causal claim lacks support",
    }
    state = _feedback_state(hypothesis)

    feedback = _specialist_feedback_for(state, hypothesis)

    assert "rescue experiment" in feedback
    assert "stronger causal controls" in feedback
    assert '"outcome": "lost"' in feedback
    assert '"hypothesis_id": "neighbor"' in feedback
    assert "partially_holds" in feedback
    assert "one causal claim lacks support" in feedback


def test_specialist_feedback_carries_mature_review_findings() -> None:
    """The parent's full/simulation reviews steer evolution (audit E1).

    A fatal finding on the parent is exactly the weakness the child must
    refine away, so its verdict and findings join the specialist ledger.
    """
    hypothesis = make_hypothesis(text="a hypothesis with mature reviews")
    hypothesis.enrichments["full"] = {
        "verdict": "rejected",
        "justification": "circular pathway",
        "retrieved_articles": [{"title": "not for the ledger"}],
    }
    hypothesis.enrichments["simulation"] = {
        "verdict": "breaks_down",
        "decisive_step": "binding fails",
        "failure_points": ["step two"],
    }
    state = _feedback_state(hypothesis)

    feedback = _specialist_feedback_for(state, hypothesis)

    ledger = json.loads(feedback)
    assert ledger["mature_reviews"]["full"]["verdict"] == "rejected"
    assert ledger["mature_reviews"]["full"]["justification"] == (
        "circular pathway"
    )
    assert ledger["mature_reviews"]["simulation"]["verdict"] == "breaks_down"
    # Retrieval bookkeeping stays out of the prompt context.
    assert "retrieved_articles" not in feedback


def test_specialist_feedback_omits_mature_reviews_before_the_cascade() -> None:
    """No mature review has run -> no "mature_reviews" key at all.

    Same omit-rather-than-hollow convention as deep verification: a
    present-but-empty block would read as "reviewed, nothing found".
    """
    hypothesis = make_hypothesis(text="a hypothesis awaiting review")
    state = _feedback_state(hypothesis)

    feedback = _specialist_feedback_for(state, hypothesis)

    assert "mature_reviews" not in json.loads(feedback)


def test_specialist_feedback_omits_deep_verification_before_it_has_run() -> (
    None
):
    """No deep-verification probes yet -> no "deep_verification" key at all.

    Regression guard: deep verification only reaches the tournament's
    leaders, so most hypotheses reach evolution before it has run. The
    ledger used to include an unconditional ``{"verdict": None, "probes":
    []}`` block for these -- indistinguishable from "checked, nothing
    found" -- instead of omitting the key the way the ranking-matchup
    prompt's equivalent projection already did.
    """
    hypothesis = make_hypothesis(text="a hypothesis awaiting verification")
    state = _feedback_state(hypothesis)

    feedback = _specialist_feedback_for(state, hypothesis)

    assert "deep_verification" not in json.loads(feedback)
