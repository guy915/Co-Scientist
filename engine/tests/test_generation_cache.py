"""Regression tests for the generation cache-collapse fix.

Background: the LLM cache key has no per-call nonce, and hypothesis generation
is stochastic (high temperature). Caching generation froze the sampled output,
so a warm cache returned the SAME hypothesis for every generation call; the
``deduplicate_hypotheses`` reducer then collapsed N identical hypotheses to one
(observed as generate=8 -> 1 on a warm-cache run). The fix routes generation
calls through ``use_cache=False`` so they bypass the cache and stay diverse
independently of cache state, while caching remains on for deterministic nodes.

These tests use ``asyncio.run`` so no pytest-asyncio configuration is needed.
"""

import asyncio
import json
from typing import Any

import co_scientist.cache as cache_mod
import co_scientist.llm as llm_mod
from co_scientist.cache import NullCache, get_cache
from co_scientist.llm import call_llm_json
from co_scientist.nodes.generation import debate
from co_scientist.nodes.generation.debate import generate_with_debate
from tests._state import make_state


def test_null_cache_is_noop() -> None:
    cache = NullCache()
    assert cache.get("anything", "m", 0.7, 100) is None
    # set is a no-op that must not raise or store anything.
    cache.set("anything", "m", 0.7, 100, {"x": 1})
    assert cache.get("anything", "m", 0.7, 100) is None


def test_call_llm_json_bypasses_warm_cache_when_disabled(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    """use_cache=False ignores a warm cache and returns a fresh LLM response."""
    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "true")
    monkeypatch.setenv("COSCIENTIST_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cache_mod, "_global_cache", None)

    schema = {"name": "x"}
    get_cache().set(
        "P", "m", 0.7, 100, {"hypotheses": [{"hypothesis": "CACHED"}]},
        json_schema=schema)

    async def fake_call_llm(  # noqa: D401 - test stub
        prompt: str,
        model_name: str,
        max_tokens: int = 4000,
        temperature: float = 0.7,
        force_json: bool = False,
        json_schema: Any = None,
        use_cache: bool = True,
    ) -> str:
        return json.dumps({"hypotheses": [{"hypothesis": "FRESH"}]})

    monkeypatch.setattr(llm_mod, "call_llm", fake_call_llm)

    cached = asyncio.run(
        call_llm_json("P", "m", max_tokens=100, temperature=0.7,
                      json_schema=schema, use_cache=True))
    assert cached["hypotheses"][0]["hypothesis"] == "CACHED"

    fresh = asyncio.run(
        call_llm_json("P", "m", max_tokens=100, temperature=0.7,
                      json_schema=schema, use_cache=False))
    assert fresh["hypotheses"][0]["hypothesis"] == "FRESH"

    monkeypatch.setattr(cache_mod, "_global_cache", None)


def test_parallel_debates_stay_distinct_with_warm_cache(
    monkeypatch: Any,
) -> None:
    """N parallel debates yield N distinct hypotheses even when the cache is
    warm -- because generation bypasses the cache.

    The fake LLM emulates the cache: a warm cache (use_cache=True) would return
    one identical response for every debate (the collapse); bypassing it
    (use_cache=False, the fix) yields a fresh, distinct response per call.
    """
    monkeypatch.setattr(debate, "get_debate_generation_prompt",
                        lambda **_: ("prompt", {"name": "x"}))
    monkeypatch.setattr(debate, "save_prompt_to_disk", lambda **_: None)
    monkeypatch.setattr(debate, "resolve_citation_keys", lambda *a, **k: {})

    async def fake_call_llm(*_a: Any, use_cache: bool = True,
                            **_k: Any) -> str:
        # Debate turns must also bypass the cache.
        assert use_cache is False
        return "turn"

    counter = {"n": 0}

    async def fake_call_llm_json(*_a: Any, use_cache: bool = True,
                                 **_k: Any) -> dict[str, Any]:
        if use_cache:
            text = "CACHED-IDENTICAL"  # warm-cache collapse (regression)
        else:
            counter["n"] += 1
            text = f"FRESH-{counter['n']}"  # fresh per call (fixed)
        return {
            "hypotheses": [{
                "hypothesis": text,
                "explanation": "",
                "experiment": "",
                "literature_grounding": "",
            }]
        }

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)

    state = make_state(research_goal="g", model_name="m")
    hyps, _ = asyncio.run(generate_with_debate(state, count=4))

    assert len(hyps) == 4
    texts = {h.text for h in hyps}
    assert len(texts) == 4, f"expected 4 distinct hypotheses, got {texts}"
