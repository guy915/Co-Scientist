import json
from typing import Any

import httpx
import pytest

from co_scientist.core.config import settings
from co_scientist.core.exceptions import ProviderAdmissionError
from co_scientist.platform.llm.decisions import DecisionSettings, SystemOneClient
from co_scientist.platform.retrieval.evidence import relevance
from co_scientist.science.prompts import get_literature_review_relevance_batch_prompt


def _papers() -> dict[str, dict[str, Any]]:
    return {
        "a": {"title": "First", "abstract": "alpha", "retrieval_score": 0.2},
        "b": {"title": "Second", "abstract": "beta", "retrieval_score": 0.8},
    }


def _install(monkeypatch: pytest.MonkeyPatch, reply: Any, *, enabled: bool = True) -> None:
    client = SystemOneClient(
        DecisionSettings(api_key="synthetic-key", enabled=enabled),
        transport=httpx.MockTransport(reply),
    )
    monkeypatch.setenv("DECISION_LITERATURE_RELEVANCE_THRESHOLD", "0.9")
    monkeypatch.setattr(
        "co_scientist.platform.llm.decisions.cascade.SystemOneClient", lambda settings: client
    )


def _response(
    request: httpx.Request, *, low: bool = False, missing: bool = False
) -> httpx.Response:
    names = list(json.loads(request.content)["questions"])
    answers = {}
    for i, name in enumerate(names):
        if missing and i:
            continue
        level = 4 if i == 0 else 0
        answers[name] = {
            "type": "score",
            "score": level,
            "confidence": 0.6 if low and i else 0.99,
            "probabilities": {str(j): int(j == level) for j in range(5)},
        }
    return httpx.Response(200, json={"model": "d1:free", "answers": answers})


async def test_accepted_batch_preserves_fusion_and_stores_decider_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _response(request)

    async def unexpected(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("accepted batch must not call the LLM")

    _install(monkeypatch, reply)
    monkeypatch.setattr(relevance, "call_llm_json", unexpected)
    papers = _papers()
    result = await relevance.apply_semantic_relevance(papers, "Goal", "offline/deterministic", 2)
    assert len(seen) == 1 and len(seen[0]["questions"]) == 2
    assert list(result) == ["a", "b"]
    assert result["a"]["retrieval_score"] == 0.6
    assert result["b"]["retrieval_score"] == 0.4
    assert result["a"]["retrieval_rationale"] == "Decided by d1:free, p=0.99"
    assert "decider=liquid/d1:free" in result["a"]["retriever_version"]


@pytest.mark.parametrize("mode", ["low", "missing", "disabled"])
async def test_one_uncertain_or_unavailable_paper_falls_back_once_for_the_entire_batch(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    calls = []

    async def llm(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "judgments": [
                {"index": 2, "relevance": 0.9, "rationale": "LLM second"},
                {"index": 1, "relevance": 0.1, "rationale": "LLM first"},
            ]
        }

    _install(
        monkeypatch,
        lambda request: _response(request, low=mode == "low", missing=mode == "missing"),
        enabled=mode != "disabled",
    )
    monkeypatch.setattr(relevance, "call_llm_json", llm)
    papers = _papers()
    result = await relevance.apply_semantic_relevance(papers, "Goal", "offline/deterministic", 2)
    assert len(calls) == 1
    assert calls[0]["prompt"] == get_literature_review_relevance_batch_prompt(
        "Goal", relevance._build_candidates_block(["a", "b"], papers)
    )
    assert result["a"]["retrieval_rationale"] == "LLM first"
    assert result["b"]["retrieval_rationale"] == "LLM second"
    assert result["a"]["retriever_version"] == relevance._HYBRID_VERSION
    assert all("semantic_decision_model" not in paper for paper in result.values())


async def test_unset_threshold_clears_prior_decider_and_runs_the_existing_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DECISION_LITERATURE_RELEVANCE_THRESHOLD", raising=False)
    papers = _papers()
    papers["a"]["semantic_decision_model"] = "liquid/d1:free"

    async def llm(**kwargs: Any) -> dict[str, Any]:
        return {"judgments": [{"index": i, "relevance": 0.5} for i in (1, 2)]}

    monkeypatch.setattr(relevance, "call_llm_json", llm)
    result = await relevance.apply_semantic_relevance(papers, "Goal", "offline/deterministic", 2)
    assert result["a"]["retriever_version"] == relevance._HYBRID_VERSION
    assert "semantic_decision_model" not in result["a"]


async def test_shared_admission_refusal_propagates_without_llm_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_llm_global_calls_per_day", 1)

    async def unexpected(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("shared exhaustion must not call the LLM")

    _install(monkeypatch, _response)
    monkeypatch.setattr(relevance, "call_llm_json", unexpected)
    await relevance.apply_semantic_relevance(_papers(), "Goal", "offline/deterministic", 2)
    with pytest.raises(ProviderAdmissionError):
        await relevance.apply_semantic_relevance(_papers(), "Goal", "offline/deterministic", 2)
