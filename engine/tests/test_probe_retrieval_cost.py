"""Probe retrieval must not re-pay the run-level relevance pass.

The model-judged relevance pass costs one LLM call per candidate, up to
``papers_to_read_count * 3``. The literature-review node spends that once
per run to choose the evidence every later agent reads. Targeted probe
retrieval runs *per hypothesis*, in three agents (deep verification,
comprehensive reflection, evolution grounding) and on every cycle, so
paying it there multiplied the same re-ranking by the pool size: live
telemetry showed a single ``full`` reflection item costing 20 LLM calls
where the review itself costs 2, and deep verification the same. These
tests pin the pass to the search that earned it.
"""

from typing import Any

import pytest

from co_scientist.agents.reflection import deep_verification_evidence as dve
from co_scientist.evidence import search
from co_scientist.evidence.search_support import (
    SearchConfig,
)
from tests._state import make_state


def _config(*, semantic_relevance_enabled: bool) -> SearchConfig:
    """Build a minimal SearchConfig differing only in the pass toggle."""
    return SearchConfig(
        tool_registry=None,
        workflow=None,
        is_multi_source=False,
        search_tool_name="search_pubmed",
        search_tool_config=None,
        source_name="pubmed",
        papers_to_read_count=6,
        is_dev_mode=False,
        research_goal="a research goal",
        model_name="offline/deterministic",
        semantic_relevance_enabled=semantic_relevance_enabled,
    )


def _ranked() -> dict[str, dict[str, Any]]:
    """Two candidates already ordered best-first by lexical score."""
    return {
        "best": {"title": "Best", "retrieval_score": 5.0},
        "worst": {"title": "Worst", "retrieval_score": 1.5},
    }


async def test_disabled_pass_costs_nothing_and_keeps_lexical_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opting out skips the pass entirely rather than judging cheaply."""
    calls = 0

    async def _never(*args: Any, **kwargs: Any) -> dict[str, dict[str, Any]]:
        nonlocal calls
        calls += 1
        return {}

    monkeypatch.setattr(search, "apply_semantic_relevance", _never)

    ranked = _ranked()
    result = await search._apply_semantic_relevance_if_enabled(
        ranked, _config(semantic_relevance_enabled=False)
    )

    assert calls == 0
    # Skipping re-ranks nothing and drops nothing: the caller's budget
    # still selects the same number of papers, in lexical order.
    assert list(result.keys()) == ["best", "worst"]


async def test_enabled_pass_still_runs_for_the_run_level_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The literature-review node keeps the pass it pays for once."""
    calls = 0

    async def _judge(
        ranked: dict[str, dict[str, Any]], *args: Any, **kwargs: Any
    ) -> dict[str, dict[str, Any]]:
        nonlocal calls
        calls += 1
        return ranked

    monkeypatch.setattr(search, "apply_semantic_relevance", _judge)

    await search._apply_semantic_relevance_if_enabled(
        _ranked(), _config(semantic_relevance_enabled=True)
    )

    assert calls == 1


async def test_probe_retrieval_opts_out_of_the_relevance_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The config probe retrieval hands to search has the pass off.

    This is the seam that covers all three per-hypothesis callers at
    once: they share ``_retrieve_probe_evidence``, so the opt-out lives
    there rather than being repeated (and forgotten) in each agent.
    """
    seen: list[SearchConfig] = []

    async def _collect(
        queries: list[str],
        state: Any,
        config: SearchConfig,
        client: Any,
        errors: list[str],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        seen.append(config)
        return {}, {}

    monkeypatch.setattr(
        "co_scientist.evidence.collection.collect_papers",
        _collect,
    )
    monkeypatch.setattr(
        "co_scientist.evidence.run_config.search_config_for",
        lambda state: _config(semantic_relevance_enabled=True),
    )

    async def _client(**kwargs: Any) -> Any:
        return object()

    monkeypatch.setattr("co_scientist.mcp_client.get_mcp_client", _client)

    await dve._retrieve_probe_evidence(
        make_state(mcp_available=True), ["a probe query"]
    )

    assert len(seen) == 1
    assert seen[0].semantic_relevance_enabled is False
    # The read budget stays the probe's own, not the run's evidence count.
    assert seen[0].papers_to_read_count == dve._MAX_PROBE_SOURCES
