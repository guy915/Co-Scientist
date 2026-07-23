"""Per-hypothesis specialist-feedback ledger for context-aware evolution.

Builds the bounded, hypothesis-specific evidence ledger (debate slices,
tournament outcomes, proximity neighbors, and deep-verification notes)
threaded into each evolution prompt. ``evolve.py`` re-exports these names
so the original ``co_scientist.agents.evolution.evolve`` import path is
unaffected.
"""

import json
from typing import Any

from co_scientist.models import Hypothesis
from co_scientist.state import WorkflowState


def _debates_for(
    state: WorkflowState, hypothesis: Hypothesis
) -> list[dict[str, Any]]:
    """Build the bounded debate-transcript slice for this hypothesis."""
    return [
        {
            "debate_id": item.get("debate_id"),
            "transcript": str(item.get("transcript") or "")[-2500:],
        }
        for item in state.get("debate_transcripts") or []
        if item.get("hypothesis_text") == hypothesis.text
    ][-2:]


def _tournament_matches_for(
    state: WorkflowState, hypothesis: Hypothesis
) -> list[dict[str, Any]]:
    """Build this hypothesis's tournament-matchup outcomes."""
    matches = []
    for item in state.get("tournament_matchups", []):
        side_a = item.get("hypothesis_a_id") == hypothesis.id
        side_b = item.get("hypothesis_b_id") == hypothesis.id
        if not side_a and not side_b:
            continue
        matches.append(
            {
                "outcome": (
                    "won" if item.get("winner_id") == hypothesis.id else "lost"
                ),
                "reasoning": item.get("reasoning") or item.get("reason"),
                "confidence": item.get("confidence"),
            }
        )
    return matches


def _proximity_neighbors_for(
    state: WorkflowState, hypothesis: Hypothesis
) -> list[dict[str, Any]]:
    """Build this hypothesis's proximity-graph neighbor list."""
    neighbors = []
    for edge in (state.get("proximity_graph") or {}).get("edges", []):
        if edge.get("source") == hypothesis.id:
            neighbor = edge.get("target")
        elif edge.get("target") == hypothesis.id:
            neighbor = edge.get("source")
        else:
            continue
        neighbors.append(
            {
                "hypothesis_id": neighbor,
                "similarity": edge.get("similarity"),
                "cluster_id": edge.get("cluster_id"),
            }
        )
    return neighbors


def _specialist_feedback_for(
    state: WorkflowState, hypothesis: Hypothesis
) -> str:
    """Build a bounded, hypothesis-specific feedback ledger for evolution."""
    verification = {
        "verdict": hypothesis.deep_verification_verdict,
        "probes": hypothesis.deep_verification_probes,
    }
    ledger = {
        "claim_evidence_gate": hypothesis.enrichments.get("claim_gate") or {},
        "debates": _debates_for(state, hypothesis),
        "tournament": _tournament_matches_for(state, hypothesis)[-8:],
        "proximity_neighbors": _proximity_neighbors_for(state, hypothesis)[:8],
        "deep_verification": verification,
    }
    return json.dumps(ledger, indent=2)[:8000]
