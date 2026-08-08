"""Fail-closed deep verification and its stored decomposition (E4, E9).

A verification that cannot be produced must record an explicit
``unverified`` verdict rather than passing silently, and a produced
verification carries the sub-assumption decomposition and
decontextualization the node was extended with.
"""

from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.reflection import deep_verification as dv
from tests._state import make_hypothesis, make_state


def _verification_response(**overrides: object) -> dict[str, object]:
    """A complete verifier response with the E4 decomposition fields."""
    response: dict[str, object] = {
        "probes": [
            {
                "question": "q",
                "answer": "a",
                "reasoning": "r",
                "assumption_is_fundamental": False,
            }
        ],
        "sub_assumptions": [
            {
                "assumption": "the target is druggable",
                "verification": "two sources show binding",
                "status": "supported",
            }
        ],
        "decontextualizations": [
            {
                "context_bound_claim": "works in HEK293 cells",
                "general_claim": "works in mammalian cells",
                "assessment": "the general claim weakens",
            }
        ],
        "verdict": "holds",
        "overall_assessment": "ok",
    }
    response.update(overrides)
    return response


async def test_failed_verification_records_explicit_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider failure fails closed: explicit verdict, no silent pass."""

    async def _boom(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("verifier unavailable")

    monkeypatch.setattr(dv, "call_llm_json", _boom)

    h = make_hypothesis(text="leader", elo_rating=2000)
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)

    assert h.deep_verification_verdict == dv.VERDICT_UNVERIFIED
    assert h.deep_verification_probes == []
    # Stale fingerprint: the next pass re-attempts instead of trusting it.
    assert h.deep_verification_fingerprint is None


async def test_degraded_verification_records_explicit_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Output that never survived validation is not a pass either.

    The degradation fallback for the node answers ``{}``; applying it as a
    verdict-less verification would leave the idea implicitly passed.
    """
    monkeypatch.setattr(dv, "call_llm_json", AsyncMock(return_value={}))

    h = make_hypothesis(text="leader", elo_rating=2000)
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)

    assert h.deep_verification_verdict == dv.VERDICT_UNVERIFIED
    assert h.deep_verification_probes == []
    assert h.deep_verification_fingerprint is None


async def test_unverified_leader_is_retried_on_the_next_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The explicit failure state does not become a permanent one."""

    async def _boom(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("verifier unavailable")

    monkeypatch.setattr(dv, "call_llm_json", _boom)
    h = make_hypothesis(text="leader", elo_rating=2000)
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)
    assert h.deep_verification_verdict == dv.VERDICT_UNVERIFIED

    monkeypatch.setattr(
        dv, "call_llm_json", AsyncMock(return_value=_verification_response())
    )
    await dv.deep_verification_node(state)

    assert h.deep_verification_verdict == "holds"
    assert h.deep_verification_probes


async def test_stale_verification_is_cleared_by_a_failed_reverification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale verdict is not carried through a failed re-verification."""

    async def _boom(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("verifier unavailable")

    monkeypatch.setattr(dv, "call_llm_json", _boom)

    h = make_hypothesis(text="leader", elo_rating=2000)
    h.deep_verification_probes = [{"question": "old"}]
    h.deep_verification_verdict = "holds"
    state = make_state(hypotheses=[h])
    h.deep_verification_fingerprint = dv.verification_fingerprint(
        h, state["model_name"]
    )
    h.text = "materially different claim"  # invalidates the fingerprint

    await dv.deep_verification_node(state)

    assert h.deep_verification_verdict == dv.VERDICT_UNVERIFIED
    assert h.deep_verification_probes == []


async def test_decomposition_and_decontextualization_are_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The E4 behaviors are captured on the hypothesis, bounded."""
    monkeypatch.setattr(
        dv, "call_llm_json", AsyncMock(return_value=_verification_response())
    )

    h = make_hypothesis(text="leader", elo_rating=2000)
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)

    record = h.enrichments["deep_verification"]
    assert record["sub_assumptions"][0]["status"] == "supported"
    assert record["decontextualizations"][0]["general_claim"] == (
        "works in mammalian cells"
    )
    assert h.deep_verification_verdict == "holds"


async def test_decomposition_lists_are_bounded_on_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over-long decomposition output cannot grow the checkpoint."""
    from co_scientist.schemas.review import (
        DEEP_VERIFICATION_MAX_DECONTEXTUALIZATIONS,
        DEEP_VERIFICATION_MAX_SUB_ASSUMPTIONS,
    )

    monkeypatch.setattr(
        dv,
        "call_llm_json",
        AsyncMock(
            return_value=_verification_response(
                sub_assumptions=[
                    {
                        "assumption": f"a{i}",
                        "verification": "v",
                        "status": "uncertain",
                    }
                    for i in range(12)
                ],
                decontextualizations=[
                    {
                        "context_bound_claim": f"c{i}",
                        "general_claim": "g",
                        "assessment": "x",
                    }
                    for i in range(9)
                ],
            )
        ),
    )

    h = make_hypothesis(text="leader", elo_rating=2000)
    state = make_state(hypotheses=[h])
    await dv.deep_verification_node(state)

    record = h.enrichments["deep_verification"]
    assert len(record["sub_assumptions"]) == (
        DEEP_VERIFICATION_MAX_SUB_ASSUMPTIONS
    )
    assert len(record["decontextualizations"]) == (
        DEEP_VERIFICATION_MAX_DECONTEXTUALIZATIONS
    )


def test_no_verification_verdict_bars_the_tournament() -> None:
    """Every verdict ranks; the worst of them is demoted, not withheld.

    "Unverified" is the fail-closed record for a verification that could
    not be produced, so barring it would let a provider outage delete
    ideas. "Undermined" is a real finding and used to bar the tournament,
    which made deep verification a second terminal gate behind the
    evidence gate; it now reports itself through ``is_undermined``, which
    demotes the idea in the published order instead.
    """
    h = make_hypothesis(text="leader", elo_rating=2000)
    h.review_disposition = "viable"
    h.deep_verification_verdict = dv.VERDICT_UNVERIFIED
    assert h.is_rankable()
    assert not h.is_undermined()

    h.deep_verification_verdict = "undermined"
    assert h.is_rankable()
    assert h.is_undermined()


def test_prompt_covers_decomposition_and_decontextualization() -> None:
    """The verifier is actually asked for the two E4 behaviors."""
    from co_scientist.prompts import get_deep_verification_prompt

    prompt, _ = get_deep_verification_prompt(
        research_goal="goal", hypothesis_text="X causes Y"
    )
    assert "Sub-assumption decomposition" in prompt
    assert "Decontextualization" in prompt
