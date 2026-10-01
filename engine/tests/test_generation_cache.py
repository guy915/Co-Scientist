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
import co_scientist.llm.call as llm_call
from co_scientist.agents.generation import debate
from co_scientist.agents.generation.debate import (
    generate_with_debate,
)
from co_scientist.cache import LLMCacheRequest, NullCache, get_cache
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
)
from tests._state import make_state


async def _fresh_call_llm(*_a: Any, **_k: Any) -> str:
    """Stand-in raw call that always returns a fresh (uncached) response.

    Accepts whatever ``call_llm_json`` passes through, like the other two
    doubles in this module; the response never depends on the arguments.
    Patched in as ``_call_llm_single_attempt`` -- the one-attempt primitive
    ``call_llm_json``'s per-attempt raw call actually runs -- rather than
    the public ``call_llm``, which now carries its own budget-escalation
    retry loop and is not what call_llm_json's attempts go through.
    """
    return json.dumps({"hypotheses": [{"hypothesis": "FRESH"}]})


def _run_json_call(schema: Any, *, use_cache: bool) -> dict[str, Any]:
    """Run ``call_llm_json`` with the fixed test parameters."""
    return asyncio.run(
        call_llm_json(
            "P",
            CompletionSpec(
                model_name="m",
                max_tokens=100,
                temperature=0.7,
                json_schema=schema,
            ),
            options=LLMCallOptions(use_cache=use_cache),
        )
    )


def test_null_cache_is_noop() -> None:
    cache = NullCache()
    assert cache.get("anything", "m", 0.7, 100) is None
    # set is a no-op that must not raise or store anything.
    request = LLMCacheRequest("anything", "m", 0.7, 100)
    cache.set(request, {"x": 1})
    assert cache.get(request) is None


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
        LLMCacheRequest("P", "m", 0.7, 100, json_schema=schema),
        {"hypotheses": [{"hypothesis": "CACHED"}]},
    )
    monkeypatch.setattr(llm_call, "_call_llm_single_attempt", _fresh_call_llm)

    cached = _run_json_call(schema, use_cache=True)
    assert cached["hypotheses"][0]["hypothesis"] == "CACHED"

    fresh = _run_json_call(schema, use_cache=False)
    assert fresh["hypotheses"][0]["hypothesis"] == "FRESH"

    monkeypatch.setattr(cache_mod, "_global_cache", None)


async def _fake_debate_call_llm(
    *_a: Any, options: Any = None, **_k: Any
) -> str:
    # Debate turns must also bypass the cache.
    assert options is not None and options.use_cache is False
    return "turn"


def _make_fake_debate_call_llm_json(counter: dict[str, int]) -> Any:
    """Build a fake ``call_llm_json`` that emulates warm-cache collapse.

    A warm cache (use_cache=True) returns one identical response for every
    debate (the collapse); bypassing it (use_cache=False, the fix) yields a
    fresh, distinct response per call, tracked via ``counter``.
    """

    async def fake_call_llm_json(
        *_a: Any, options: Any = None, **_k: Any
    ) -> dict[str, Any]:
        use_cache = options.use_cache if options is not None else True
        if use_cache:
            text = "CACHED-IDENTICAL"  # warm-cache collapse (regression)
        else:
            counter["n"] += 1
            text = f"FRESH-{counter['n']}"  # fresh per call (fixed)
        return {
            "hypotheses": [
                {
                    "hypothesis": text,
                    "explanation": "",
                    "experiment": "",
                    "literature_grounding": "",
                }
            ]
        }

    return fake_call_llm_json


def test_parallel_debates_stay_distinct_with_warm_cache(
    monkeypatch: Any,
) -> None:
    """N parallel debates yield N distinct hypotheses with a warm cache.

    Distinctness holds because generation bypasses the cache.
    """
    monkeypatch.setattr(
        debate,
        "get_debate_generation_prompt",
        lambda *_a, **_k: ("prompt", {"name": "x"}),
    )
    monkeypatch.setattr(debate, "call_llm", _fake_debate_call_llm)
    monkeypatch.setattr(
        debate, "call_llm_json", _make_fake_debate_call_llm_json({"n": 0})
    )

    state = make_state(research_goal="g", model_name="m")
    hyps, _, _ = asyncio.run(generate_with_debate(state, count=4))

    assert len(hyps) == 4
    texts = {h.text for h in hyps}
    assert len(texts) == 4, f"expected 4 distinct hypotheses, got {texts}"
