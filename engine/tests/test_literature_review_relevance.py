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
from co_scientist.cache import scoped_cache_override
from co_scientist.evidence import relevance, search, search_query
from co_scientist.evidence.relevance import _HYBRID_VERSION
from co_scientist.mcp_client import CampaignToolUnavailableError, MCPToolClient
from co_scientist.offline import llm as offline_llm
from co_scientist.tools.response_parser import parse_mcp_result
from tests._llm_fake import mock_call_llm_json, stub_call_llm_json
from tests._mcp import isolate_offline_router
from tests._research_fakes import _stub_node, make_search_config
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


@pytest.fixture
def _literature_review_search_single_source_isolate_offline_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_offline_router(monkeypatch)
    offline_llm.install_offline_router()


_OVERFETCH_RESULTS: list[dict[str, dict[str, Any]]] = [
    {
        "p1": {"title": "Shared paper", "source": "pubmed", "year": 2025},
        "p2": {
            "title": "Independent paper",
            "source": "pubmed",
            "year": 2024,
        },
    },
    {
        "duplicate": {
            "title": "shared paper",
            "source": "pubmed",
            "year": 2025,
        },
        "p3": {"title": "Third paper", "source": "pubmed", "year": 2023},
        "retracted": {
            "title": "Retracted paper",
            "source": "pubmed",
            "year": 2026,
            "is_retracted": True,
        },
    },
]


def _recording_search_all_queries(observed: dict[str, int]) -> Any:

    async def fake_search_all_queries(
        queries: list[str],
        papers_per_query: int,
        *_args: Any,
        **_kwargs: Any,
    ) -> list[dict[str, dict[str, Any]]]:
        observed["queries"] = len(queries)
        observed["papers_per_query"] = papers_per_query
        return _OVERFETCH_RESULTS

    return fake_search_all_queries


@pytest.mark.usefixtures(
    "_literature_review_search_single_source_isolate_offline_router"
)
class TestLiteratureReviewSearchSingleSource:
    @pytest.mark.asyncio
    async def test_single_source_overfetches_dedupes_ranks_and_caps(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        observed: dict[str, int] = {}
        monkeypatch.setattr(
            search,
            "_search_all_queries",
            _recording_search_all_queries(observed),
        )
        config = make_search_config(
            search_tool_name="pubmed_fulltext",
            source_name="pubmed",
            papers_to_read_count=3,
        )

        papers, source_map = await search._phase2_collect_papers_single_source(
            ["expanded one", "expanded two"],
            config,
            search._SearchRunContext(
                slug="slug",
                run_id="run-1",
                mcp_client=cast(MCPToolClient, object()),
            ),
        )

        assert observed == {"queries": 2, "papers_per_query": 3}
        assert list(papers) == ["p1", "p2", "p3"]
        assert "duplicate" not in papers
        assert "retracted" not in papers
        assert source_map == {}

    @pytest.mark.asyncio
    async def test_single_source_hybrid_scores_when_goal_is_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        observed: dict[str, int] = {}
        monkeypatch.setattr(
            search,
            "_search_all_queries",
            _recording_search_all_queries(observed),
        )
        config = make_search_config(
            search_tool_name="pubmed_fulltext",
            source_name="pubmed",
            papers_to_read_count=3,
            research_goal="a research goal",
            model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
        )

        papers, _ = await search._phase2_collect_papers_single_source(
            ["expanded one", "expanded two"],
            config,
            search._SearchRunContext(
                slug="slug",
                run_id="run-1",
                mcp_client=cast(MCPToolClient, object()),
            ),
        )

        assert list(papers) == ["p1", "p2", "p3"]
        for metadata in papers.values():
            assert 0.0 <= metadata["retrieval_score"] <= 1.0
            assert metadata["retriever_version"] == _HYBRID_VERSION


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


class _ToolErrorClient:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls = 0

    async def call_tool(self, _name: str, **_params: Any) -> Any:
        self.calls += 1
        return self.payload


@pytest.mark.usefixtures("_no_real_sleep")
class TestLiteratureReviewSearchRetry:
    @pytest.mark.asyncio
    async def test_a_source_survives_more_than_one_transient_failure(
        self,
    ) -> None:
        client = _FlakyClient(failures=2)

        result = await search_query._call_search_tool(
            cast(MCPToolClient, client), "search_pubmed", {}
        )

        assert result == {"papers": []}
        assert client.calls == 3

    @pytest.mark.asyncio
    async def test_exhausted_retries_still_raise_to_the_caller(self) -> None:
        """Callers must distinguish failed searches from successful empty
        results."""
        client = _FlakyClient(failures=search_query._SEARCH_ATTEMPTS)

        with pytest.raises(RuntimeError, match="throttling"):
            await search_query._call_search_tool(
                cast(MCPToolClient, client), "search_pubmed", {}
            )

        assert client.calls == search_query._SEARCH_ATTEMPTS

    @pytest.mark.asyncio
    async def test_backoff_grows_and_is_jittered(
        self,
        _no_real_sleep: list[float],
    ) -> None:
        """Fixed schedules release throttled waves together and recreate their
        burst."""
        client = _FlakyClient(failures=search_query._SEARCH_ATTEMPTS - 1)
        await search_query._call_search_tool(
            cast(MCPToolClient, client), "search_pubmed", {}
        )
        first = list(_no_real_sleep)
        _no_real_sleep.clear()

        client2 = _FlakyClient(failures=search_query._SEARCH_ATTEMPTS - 1)
        await search_query._call_search_tool(
            cast(MCPToolClient, client2), "search_pubmed", {}
        )

        assert len(first) == search_query._SEARCH_ATTEMPTS - 1
        assert first == sorted(first)
        assert sum(first) > 4 * 0.25
        assert first != _no_real_sleep

    @pytest.mark.asyncio
    async def test_a_tool_reported_error_is_not_retried(self) -> None:
        """MCP tool errors are rejected queries, not transient transport
        failures."""
        client = _ToolErrorClient(
            "Error calling tool 'search_openalex': OpenAlex could not be "
            "searched: HTTP 400; Wildcards (* or ?) require exact (no-stem) "
            "search."
        )

        with pytest.raises(ToolException, match="HTTP 400"):
            await search_query._call_search_tool(
                cast(MCPToolClient, client), "search_openalex", {}
            )
        assert client.calls == 1

    @pytest.mark.asyncio
    async def test_a_timeout_still_retries_despite_the_new_permanent_path(
        self,
    ) -> None:
        client = _FlakyClient(failures=2)

        result = await search_query._call_search_tool(
            cast(MCPToolClient, client), "search_openalex", {}
        )

        assert result == {"papers": []}
        assert client.calls == 3

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
        self, payload: str, expected: str
    ) -> None:
        """Payloads distinguish gateway pages, throttling notices and empty
        bodies."""
        with pytest.raises(json.JSONDecodeError) as caught:
            parse_mcp_result(payload)

        assert expected in str(caught.value)

    @pytest.mark.asyncio
    async def test_sdk_tool_failure_preserves_provenance_without_retry(
        self,
    ) -> None:
        class Client:
            calls = 0

            async def call_tool(self, _name: str, **_params: Any) -> Any:
                self.calls += 1
                raise ToolException(
                    "Europe PMC unavailable: HTTP 429; Retry-After=60"
                )

        client = Client()
        with pytest.raises(ToolException, match="Retry-After=60"):
            await search_query._call_search_tool(
                cast(MCPToolClient, client), "search_europepmc", {}
            )
        assert client.calls == 1

    @pytest.mark.asyncio
    async def test_a_campaign_policy_refusal_is_not_retried(self) -> None:
        """Campaign policy refuses identically on every attempt."""

        class _RefusingClient:
            calls = 0

            async def call_tool(self, _name: str, **_params: Any) -> Any:
                self.calls += 1
                raise CampaignToolUnavailableError(
                    "tool is unavailable under campaign MCP policy"
                )

        client = _RefusingClient()

        with pytest.raises(CampaignToolUnavailableError):
            await search_query._call_search_tool(
                cast(MCPToolClient, client), "search_web", {}
            )

        assert client.calls == 1
