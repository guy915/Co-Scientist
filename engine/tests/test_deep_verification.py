"""Tests for the deep-verification node.

The node runs probing-question deep verification on the top-k hypotheses by
Elo. These tests monkeypatch ``call_llm_json`` on the node module so no LLM or
network calls are made, and assert that only the highest-Elo hypotheses are
verified and that already-verified hypotheses are skipped.
"""

from unittest.mock import AsyncMock

import pytest

from co_scientist.nodes import deep_verification as dv
from tests._state import make_hypothesis, make_state


async def test_verifies_only_top_k_by_elo(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the three highest-Elo hypotheses receive probes."""
    fake = AsyncMock(
        return_value={
            "probes": [{
                "question": "q",
                "answer": "a",
                "reasoning": "r",
                "assumption_is_fundamental": True,
            }],
            "verdict": "weakened",
            "overall_assessment": "ok",
        })
    monkeypatch.setattr(dv, "call_llm_json", fake)

    hyps = [
        make_hypothesis(text=f"h{i}", elo_rating=1000 + i * 100)
        for i in range(5)  # elos 1000..1400
    ]
    state = make_state(hypotheses=hyps,
                       research_goal="goal",
                       model_name="test/model",
                       run_id="r1")
    out = await dv.deep_verification_node(state)

    verified = [h for h in out["hypotheses"] if h.deep_verification_probes]
    # DEEP_VERIFICATION_TOP_K == 3 -> only the three highest-Elo get probes.
    assert len(verified) == 3
    assert {h.text for h in verified} == {"h4", "h3", "h2"}
    assert verified[0].deep_verification_verdict == "weakened"
    assert fake.await_count == 3


async def test_skips_already_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hypothesis that already has probes is not re-verified."""
    fake = AsyncMock(
        return_value={
            "probes": [{
                "question": "q",
                "answer": "a",
                "reasoning": "r",
                "assumption_is_fundamental": False,
            }],
            "verdict": "holds",
            "overall_assessment": "ok",
        })
    monkeypatch.setattr(dv, "call_llm_json", fake)

    h = make_hypothesis(text="already", elo_rating=2000)
    h.deep_verification_probes = [{
        "question": "old",
        "answer": "a",
        "reasoning": "r",
        "assumption_is_fundamental": True,
    }]
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)
    assert fake.await_count == 0  # already has probes -> skipped
