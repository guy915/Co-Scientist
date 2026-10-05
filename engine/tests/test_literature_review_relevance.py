from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any, cast

import pytest
from langchain_core.tools import ToolException

from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.cache import scoped_cache_override
from co_scientist.evidence import relevance, search, search_query
from co_scientist.mcp_client import CampaignToolUnavailableError, MCPToolClient
from co_scientist.offline import llm as offline_llm
from co_scientist.tools.response_parser import parse_mcp_result
from tests._llm_fake import mock_call_llm_json, stub_call_llm_json
from tests._mcp import isolate_offline_router
from tests._research_fakes import _make_event_recorder, _stub_node
from tests._state import make_state


@pytest.fixture
def _literature_review_relevance_isolate_offline_router(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    isolate_offline_router(monkeypatch)
    offline_llm.install_offline_router()
    # Warm disk entries would bypass the judgments these tests exercise.
    with scoped_cache_override(False):
        yield


def _candidate(title: str, lexical_score: float) -> dict[str, object]:
    return {
        "title": title,
        "abstract": f"Abstract for {title}.",
        "retrieval_score": lexical_score,
    }


def _stub_judgments(*, count: int, start_relevance: float = 0.0) -> list[Any]:
    return [
        {
            "index": i,
            "relevance": start_relevance + i,
            "rationale": f"reason {i}",
        }
        for i in range(1, count + 1)
    ]


def _pool(n: int) -> dict[str, dict[str, object]]:
    return {
        f"p{i}": _candidate(f"Paper {i}", 1.0 - i / (n + 1))
        for i in range(1, n + 1)
    }


async def _ranked_review(
    monkeypatch: pytest.MonkeyPatch,
    pool: dict[str, Any],
    *,
    goal: str = "goal",
    count: int | None = None,
) -> dict[str, Any]:
    _stub_node(monkeypatch, server_available=True, search_payload=pool)
    monkeypatch.setattr(
        search, "merge_search_results", lambda *args, **kwargs: (pool, {})
    )
    result = await literature_review_node(
        make_state(
            research_goal=goal,
            model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
            literature_review_papers_count=len(pool)
            if count is None
            else count,
        )
    )
    return {article.source_id: article for article in result["articles"]}


@pytest.mark.usefixtures("_literature_review_relevance_isolate_offline_router")
@pytest.mark.parametrize("goal", ["goal", ""])
async def test_review_preserves_lexical_differences_and_retrieval_method(
    monkeypatch: pytest.MonkeyPatch,
    goal: str,
) -> None:
    first = await _ranked_review(
        monkeypatch,
        {"best": _candidate("Best", 1.0), "worst": _candidate("Worst", 0.0)},
        goal=goal,
    )
    second = await _ranked_review(
        monkeypatch,
        {"best": _candidate("Best", 1.0), "worst": _candidate("Worst", 0.0)},
        goal=goal,
    )
    assert list(first) == list(second)
    assert first["best"].retrieval_score == 1.0
    assert first["worst"].retrieval_score == (0.5 if goal else 0.0)
    for paper_id, article in first.items():
        assert article.retriever_version == (
            relevance._HYBRID_VERSION
            if goal
            else relevance._LEXICAL_ONLY_VERSION
        )
        assert article.retrieval_score == second[paper_id].retrieval_score
        assert (
            article.retrieval_rationale == second[paper_id].retrieval_rationale
        )


@pytest.mark.parametrize(
    ("judgments", "expected"),
    [
        (
            [
                {"index": 3, "relevance": 0.3, "rationale": "third"},
                {"index": 1, "relevance": 0.9, "rationale": "first"},
                {"index": 2, "relevance": 0.1, "rationale": "second"},
            ],
            ["first", "second", "third"],
        ),
        (
            [
                {"relevance": 0.5, "rationale": "no index"},
                {"index": 1, "relevance": 0.9, "rationale": "explicit"},
            ],
            ["explicit", "no index", "semantic relevance scoring failed"],
        ),
        (
            [
                {"index": 1, "relevance": 0.9, "rationale": "first claim"},
                {"index": 1, "relevance": 0.1, "rationale": "duplicate claim"},
            ],
            [
                "first claim",
                "duplicate claim",
                "semantic relevance scoring failed",
            ],
        ),
        (
            [
                {"index": 1, "relevance": "n/a"},
                {"index": 2, "relevance": 0.8, "rationale": "fine"},
            ],
            [
                "semantic relevance scoring failed",
                "fine",
                "semantic relevance scoring failed",
            ],
        ),
        (
            [{"index": 1, "relevance": 0.7, "rationale": "ok"}],
            [
                "ok",
                "semantic relevance scoring failed",
                "semantic relevance scoring failed",
            ],
        ),
    ],
    ids=[
        "reordered",
        "missing-index",
        "duplicate-index",
        "bad-type",
        "short-array",
    ],
)
async def test_review_assigns_malformed_judgments_to_the_right_papers(
    monkeypatch: pytest.MonkeyPatch,
    judgments: list[Any],
    expected: list[str],
) -> None:
    stub_call_llm_json(monkeypatch, relevance, {"judgments": judgments})
    papers = await _ranked_review(monkeypatch, _pool(3))
    assert [
        papers[f"p{i}"].retrieval_rationale for i in range(1, 4)
    ] == expected
    assert all(
        article.retriever_version == relevance._HYBRID_VERSION
        for article in papers.values()
    )


@pytest.mark.parametrize("semantic", [-2.0, 4.0])
async def test_review_clamps_provider_relevance_to_the_scoring_range(
    monkeypatch: pytest.MonkeyPatch,
    semantic: float,
) -> None:
    stub_call_llm_json(
        monkeypatch,
        relevance,
        {"judgments": [{"index": 1, "relevance": semantic}]},
    )
    papers = await _ranked_review(monkeypatch, {"p": _candidate("Paper", 0.5)})
    assert papers["p"].retrieval_score == (0.25 if semantic < 0 else 0.75)


async def test_review_bounds_semantic_cost_and_preserves_unscored_papers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates: list[int] = []

    async def judge(*, prompt: str, **_: Any) -> dict[str, Any]:
        count = prompt.count("**Candidate ")
        candidates.append(count)
        return {"judgments": _stub_judgments(count=count)}

    monkeypatch.setattr(relevance, "call_llm_json", judge)
    papers = await _ranked_review(monkeypatch, _pool(25))
    assert len(papers) == 25
    assert sum(candidates) == 24
    assert max(candidates) <= 10
    assert papers["p25"].retriever_version == relevance._LEXICAL_ONLY_VERSION


async def test_review_semantic_failure_preserves_lexical_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_call_llm_json(
        monkeypatch, relevance, side_effect=RuntimeError("provider exploded")
    )
    papers = await _ranked_review(monkeypatch, _pool(2))
    assert len(papers) == 2
    assert all(
        article.retrieval_rationale == relevance._FAILED_JUDGMENT_RATIONALE
        for article in papers.values()
    )


async def test_review_with_negative_budget_keeps_only_lexical_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_judgment(**_: Any) -> Any:
        pytest.fail("A nonpositive budget must not purchase semantic judgments")

    monkeypatch.setattr(relevance, "call_llm_json", unexpected_judgment)
    result = await _ranked_review(
        monkeypatch,
        {
            "low": _candidate("Low", -0.2),
            "high": _candidate("High", 1.5),
            "spare": _candidate("Spare", 0.5),
        },
        count=-1,
    )
    assert result["low"].retrieval_score == 0.0
    assert result["high"].retrieval_score == 1.0
    assert all(
        article.retriever_version == relevance._LEXICAL_ONLY_VERSION
        for article in result.values()
    )


class _FlakyClient:
    def __init__(self, failures: int, payload: Any = None) -> None:
        self.failures = failures
        self.payload = payload if payload is not None else {"papers": []}
        self.calls = 0

    async def call_tool(self, _name: str, **_params: Any) -> Any:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("upstream is throttling")
        return self.payload


@pytest.fixture
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []

    async def _record(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _record)
    return slept


class _ScriptedSearchClient:
    """Answers every search call from a script and counts the calls."""

    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.calls = 0

    async def call_tool(self, _name: str, **_params: Any) -> Any:
        self.calls += 1
        outcome = self.script[min(self.calls, len(self.script)) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


_PAPER = {"paper": {"title": "Recovered", "abstract": "Measured result"}}
_ATTEMPTS = search_query._SEARCH_ATTEMPTS


@pytest.mark.usefixtures("_no_real_sleep")
@pytest.mark.parametrize(
    ("script", "calls", "found", "reported"),
    [
        # Transient transport failures are retried, even several in a row.
        ([RuntimeError("throttling")] * 2 + [_PAPER], 3, True, None),
        ([RuntimeError("throttling")], _ATTEMPTS, False, "throttling"),
        # A malformed transport result is a transient failure too.
        (["429 Too Many Requests", _PAPER], 2, True, None),
        # MCP tool errors are rejected queries, not transient failures.
        (
            [
                "Error calling tool 'search_openalex': OpenAlex could not be "
                "searched: HTTP 400; Wildcards (* or ?) require exact search."
            ],
            1,
            False,
            "HTTP 400",
        ),
        (
            [ToolException("Europe PMC unavailable: HTTP 429; Retry-After=60")],
            1,
            False,
            "Retry-After=60",
        ),
        # Campaign policy refuses identically on every attempt.
        (
            [CampaignToolUnavailableError("unavailable under campaign policy")],
            1,
            False,
            "campaign policy",
        ),
    ],
    ids=[
        "transient-recovers",
        "exhausted",
        "malformed-result-recovers",
        "tool-error",
        "sdk-tool-failure",
        "campaign-refusal",
    ],
)
async def test_review_retries_only_failures_that_may_be_transient(
    monkeypatch: pytest.MonkeyPatch,
    script: list[Any],
    calls: int,
    found: bool,
    reported: str | None,
) -> None:
    """Callers must distinguish failed searches from successful empty
    results."""
    _stub_node(monkeypatch, server_available=True, queries=["q"])
    client = _ScriptedSearchClient(*script)
    events, callback = _make_event_recorder()

    async def get_client(**_: Any) -> Any:
        return client

    monkeypatch.setattr(lr, "get_mcp_client", get_client)

    result = await literature_review_node(
        make_state(progress_callback=callback)
    )

    assert client.calls == calls
    assert bool(result["articles"]) is found
    failures = [p for e, p in events if e == "literature_review_error"]
    if reported is None:
        assert not failures
    else:
        assert reported in str(failures[0]["search_error_sample"])


async def test_backoff_grows_and_is_jittered(
    _no_real_sleep: list[float],
) -> None:
    """Fixed schedules release throttled waves together and recreate their
    burst."""

    async def one_throttled_search() -> list[float]:
        _no_real_sleep.clear()
        client = cast(MCPToolClient, _FlakyClient(failures=_ATTEMPTS - 1))
        await search_query._call_search_tool(client, "search_pubmed", {})
        return list(_no_real_sleep)

    first = await one_throttled_search()
    second = await one_throttled_search()

    assert len(first) == _ATTEMPTS - 1
    assert first == sorted(first)
    assert sum(first) > 4 * 0.25
    assert first != second


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("<html><title>502 Bad Gateway</title></html>", "502 Bad Gateway"),
        ("Too Many Requests. Retry later.", "Too Many Requests"),
        ("", "empty"),
    ],
    ids=["gateway_error_page", "throttling_notice", "empty_body"],
)
def test_undecodable_payload_is_quoted_in_the_error(
    payload: str, expected: str
) -> None:
    """Payloads distinguish gateway pages, throttling notices and empty
    bodies."""
    with pytest.raises(json.JSONDecodeError) as caught:
        parse_mcp_result(payload)

    assert expected in str(caught.value)
