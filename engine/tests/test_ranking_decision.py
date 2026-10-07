import asyncio
import json
from typing import Any

import httpx
import pytest

from co_scientist.core.config import settings
from co_scientist.core.exceptions import ProviderAdmissionError
from co_scientist.domains.research_state.models.matchup import Matchup
from co_scientist.platform.llm.decisions import DecisionSettings, SystemOneClient
from co_scientist.science.ranking import ranking_debate
from co_scientist.science.ranking.operations import RankingJudgement, apply_ranking_matchup
from tests._state import make_hypothesis, make_ranking_response


def _context(index: int = 0) -> ranking_debate._DebateContext:
    return ranking_debate._DebateContext(
        make_hypothesis(text="Mechanism alpha through enzyme inhibition"),
        make_hypothesis(text="Mechanism beta through receptor activation"),
        "Research goal",
        "offline/deterministic",
        matchup_index=index,
    )


def _answer(choice: str, probability: float = 0.95) -> dict[str, Any]:
    return {
        "model": "d1:free",
        "answers": {
            "winner": {
                "type": "choice",
                "choice": choice,
                "confidence": probability,
                "probabilities": {
                    "A": probability if choice == "A" else 1 - probability,
                    "B": probability if choice == "B" else 1 - probability,
                },
            }
        },
    }


def _install(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> SystemOneClient:
    client = SystemOneClient(
        DecisionSettings(api_key="synthetic-key", enabled=True), transport=transport
    )
    monkeypatch.setenv("DECISION_RANKING_THRESHOLD", "0.9")
    monkeypatch.setattr(
        "co_scientist.platform.llm.decisions.cascade.SystemOneClient", lambda settings: client
    )
    return client


async def test_pairwise_orders_are_swapped_and_provenance_survives_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _context()
    prompts: list[str] = []

    def reply(request: httpx.Request) -> httpx.Response:
        prompts.append(json.loads(request.content)["state"])
        return httpx.Response(200, json=_answer("A" if len(prompts) == 1 else "B"))

    client = _install(monkeypatch, httpx.MockTransport(reply))

    async def unexpected(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("accepted decisions must not call the LLM")

    monkeypatch.setattr(ranking_debate, "call_llm_json", unexpected)
    winner, response = await ranking_debate.judge_matchup(ctx)
    assert winner == "a"
    assert prompts[0].index(ctx.hypothesis_a.text) < prompts[0].index(ctx.hypothesis_b.text)
    assert prompts[1].index(ctx.hypothesis_b.text) < prompts[1].index(ctx.hypothesis_a.text)
    assert client.requests == response["physical_calls"] == 2
    assert response["debate_turns"] == 1
    match = apply_ranking_matchup(
        (ctx.hypothesis_a, ctx.hypothesis_b),
        RankingJudgement(winner, response, 1),
        k_factor=32,
        current_iteration=0,
    )
    assert match.llm_calls == 2
    restored = Matchup.from_dict(match.detail)
    assert restored.judge_model == "liquid/d1:free"
    assert restored.reasoning == "Decided by d1:free, p=0.95"
    assert restored.position_balanced
    assert restored.debate_transcript[0]["decision_provider"] == "liquid"
    assert restored.debate_transcript[0]["physical_requests"] == 2


@pytest.mark.parametrize("index", [0, 1])
async def test_order_disagreement_falls_back_to_the_identical_llm_prompt(
    monkeypatch: pytest.MonkeyPatch, index: int
) -> None:
    ctx = _context(index)
    seen: list[str] = []

    async def llm(*, prompt: str, **kwargs: Any) -> dict[str, Any]:
        seen.append(prompt)
        return make_ranking_response("a", decision_summary="Existing rationale")

    monkeypatch.setattr(ranking_debate, "call_llm_json", llm)
    monkeypatch.delenv("DECISION_RANKING_THRESHOLD", raising=False)
    original_winner, original = await ranking_debate.judge_matchup(ctx)
    client = _install(
        monkeypatch, httpx.MockTransport(lambda request: httpx.Response(200, json=_answer("A")))
    )
    winner, response = await ranking_debate.judge_matchup(ctx)
    assert winner == original_winner
    assert seen[0] == seen[1]
    assert response["decision_summary"] == original["decision_summary"]
    assert response["judge_model"] == original["judge_model"]
    assert client.requests == 2
    assert response["physical_calls"] == 3


@pytest.mark.parametrize("threshold", ["", "nan", "0.5", "invalid"])
async def test_unvalidated_ranking_never_builds_a_decision_client(
    monkeypatch: pytest.MonkeyPatch, threshold: str
) -> None:
    monkeypatch.setenv("DECISION_RANKING_THRESHOLD", threshold)

    def unexpected(*args: Any) -> SystemOneClient:
        raise AssertionError("no calibrated threshold")

    monkeypatch.setattr("co_scientist.platform.llm.decisions.cascade.SystemOneClient", unexpected)

    async def llm(**kwargs: Any) -> dict[str, Any]:
        return make_ranking_response("a")

    monkeypatch.setattr(ranking_debate, "call_llm_json", llm)
    _, response = await ranking_debate.judge_matchup(_context())
    assert "physical_calls" not in response
    assert response["judge_model"] == "offline/deterministic"


async def test_top_pair_debate_stays_on_llm_even_with_a_decision_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECISION_RANKING_THRESHOLD", "0.9")

    def unexpected(*args: Any) -> SystemOneClient:
        raise AssertionError("debates are not decision calls")

    monkeypatch.setattr("co_scientist.platform.llm.decisions.cascade.SystemOneClient", unexpected)
    calls = 0

    async def llm(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return make_ranking_response("a" if calls % 2 else "b")

    monkeypatch.setattr(ranking_debate, "call_llm_json", llm)
    _, response = await ranking_debate.judge_matchup(_context(), debate_turns=10)
    assert calls == response["debate_turns"] == 3
    assert "physical_calls" not in response
    assert response["judge_model"] == "offline/deterministic"


async def test_oversized_review_state_reaches_the_llm_in_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _context()._replace(hypothesis_a=make_hypothesis(text="complete text " * 4000))
    client = _install(
        monkeypatch, httpx.MockTransport(lambda request: httpx.Response(200, json=_answer("A")))
    )
    seen = []

    async def llm(*, prompt: str, **kwargs: Any) -> dict[str, Any]:
        seen.append(prompt)
        return make_ranking_response("a")

    monkeypatch.setattr(ranking_debate, "call_llm_json", llm)
    await ranking_debate.judge_matchup(ctx)
    assert client.requests == 0
    assert ctx.hypothesis_a.text in seen[0]


async def test_shared_admission_denial_cannot_be_bypassed_by_ranking_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_llm_global_calls_per_day", 1)
    client = _install(
        monkeypatch, httpx.MockTransport(lambda request: httpx.Response(200, json=_answer("A")))
    )

    async def unexpected(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("shared admission denial is terminal")

    monkeypatch.setattr(ranking_debate, "call_llm_json", unexpected)
    with pytest.raises(ProviderAdmissionError):
        await ranking_debate.judge_matchup(_context())
    assert client.requests == 1


async def test_cancel_between_orders_never_starts_the_llm_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiting = asyncio.Event()
    never = asyncio.Event()
    calls = 0

    async def reply(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 2:
            waiting.set()
            await never.wait()
        return httpx.Response(200, json=_answer("A"))

    _install(monkeypatch, httpx.MockTransport(reply))

    async def unexpected(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("cancellation must propagate")

    monkeypatch.setattr(ranking_debate, "call_llm_json", unexpected)
    task = asyncio.create_task(ranking_debate.judge_matchup(_context()))
    await asyncio.wait_for(waiting.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
