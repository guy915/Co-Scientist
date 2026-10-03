from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import pytest
from langchain_core.tools import ToolException

from co_scientist.evidence import relevance, search, search_query
from co_scientist.evidence.relevance import _HYBRID_VERSION
from co_scientist.evidence.search_support import SearchConfig
from co_scientist.mcp_client import CampaignToolUnavailableError, MCPToolClient
from co_scientist.offline import llm as offline_llm
from co_scientist.tools.response_parser import parse_mcp_result
from tests._mcp import isolate_offline_router


@pytest.fixture
def _literature_review_relevance_isolate_offline_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_offline_router(monkeypatch)
    offline_llm.install_offline_router()


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


@pytest.mark.usefixtures("_literature_review_relevance_isolate_offline_router")
class TestLiteratureReviewRelevance:
    def test_normalize_lexical_clamps_to_documented_range(self) -> None:
        assert relevance.normalize_lexical(0.0) == 0.0
        assert relevance.normalize_lexical(1.0) == 1.0
        assert relevance.normalize_lexical(0.5) == 0.5
        assert relevance.normalize_lexical(-0.2) == 0.0
        assert relevance.normalize_lexical(1.5) == 1.0

    def test_combine_hybrid_score_without_semantic_is_lexical_only(
        self,
    ) -> None:
        assert relevance.combine_hybrid_score(0.5, None) == 0.5

    def test_combine_hybrid_score_averages_lexical_and_semantic(self) -> None:
        assert relevance.combine_hybrid_score(0.5, 1.0) == 0.75
        assert relevance.combine_hybrid_score(0.0, 0.0) == 0.0

    def test_combine_hybrid_score_clamps_out_of_range_semantic(self) -> None:
        assert relevance.combine_hybrid_score(
            0.5, 4.0
        ) == relevance.combine_hybrid_score(0.5, 1.0)
        assert relevance.combine_hybrid_score(
            0.5, -2.0
        ) == relevance.combine_hybrid_score(0.5, 0.0)

    def test_semantic_pool_size_is_bounded(self) -> None:
        assert relevance._semantic_pool_size(1000, budget=50) == (
            relevance._SEMANTIC_POOL_CAP
        )
        assert relevance._semantic_pool_size(2, budget=50) == 2
        assert relevance._semantic_pool_size(1000, budget=0) == 0

    async def test_apply_semantic_relevance_stamps_every_candidate(
        self,
    ) -> None:
        ranked = {
            "p1": _candidate("Paper One", 1.0),
            "p2": _candidate("Paper Two", 0.0),
        }
        result = await relevance.apply_semantic_relevance(
            ranked,
            research_goal="a research goal",
            model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
            budget=5,
        )
        for metadata in result.values():
            assert 0.0 <= metadata["retrieval_score"] <= 1.0
            assert metadata["retriever_version"] == relevance._HYBRID_VERSION
            assert isinstance(metadata["retrieval_rationale"], str)

    async def test_apply_semantic_relevance_skips_pool_without_goal(
        self,
    ) -> None:
        ranked = {"p1": _candidate("Paper One", 1.0)}
        result = await relevance.apply_semantic_relevance(
            ranked,
            research_goal="",
            model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
            budget=5,
        )
        assert result["p1"]["retrieval_score"] == 1.0
        assert (
            result["p1"]["retriever_version"] == relevance._LEXICAL_ONLY_VERSION
        )

    async def test_apply_semantic_relevance_preserves_lexical_differentiation(
        self,
    ) -> None:
        """Scoring a combined baseline twice erases lexical differences."""
        ranked = {
            "best": _candidate("Best lexical", 1.0),
            "worst": _candidate("Worst lexical", 0.0),
        }
        result = await relevance.apply_semantic_relevance(
            ranked,
            research_goal="a research goal",
            model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
            budget=5,
        )
        assert (
            result["best"]["retrieval_score"]
            > result["worst"]["retrieval_score"]
        )
        # Offline relevance clamps to the same 1.0 for both candidates;
        # final-score differences must come from the lexical term.
        assert result["best"][
            "retrieval_score"
        ] == relevance.combine_hybrid_score(1.0, 1.0)
        assert result["worst"][
            "retrieval_score"
        ] == relevance.combine_hybrid_score(0.0, 1.0)

    async def test_apply_semantic_relevance_bounds_pool_by_budget(self) -> None:
        ranked = {
            "best": _candidate("Best", 1.0),
            "worst": _candidate("Worst", 0.0),
        }
        result = await relevance.apply_semantic_relevance(
            ranked,
            research_goal="a research goal",
            model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
            budget=0,
        )
        assert result["best"]["retriever_version"] == (
            relevance._LEXICAL_ONLY_VERSION
        )
        assert result["worst"]["retriever_version"] == (
            relevance._LEXICAL_ONLY_VERSION
        )

    async def test_apply_semantic_relevance_is_deterministic(self) -> None:
        ranked = {
            "p1": _candidate("Paper One", 0.8),
            "p2": _candidate("Paper Two", 0.4),
        }
        first = await relevance.apply_semantic_relevance(
            {k: dict(v) for k, v in ranked.items()},
            research_goal="a fixed research goal",
            model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
            budget=5,
        )
        second = await relevance.apply_semantic_relevance(
            {k: dict(v) for k, v in ranked.items()},
            research_goal="a fixed research goal",
            model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
            budget=5,
        )
        assert list(first.keys()) == list(second.keys())
        for key in first:
            assert (
                first[key]["retrieval_score"] == second[key]["retrieval_score"]
            )
            assert (
                first[key]["retrieval_rationale"]
                == second[key]["retrieval_rationale"]
            )

    async def test_apply_semantic_relevance_batches_calls_by_batch_size(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(relevance, "_RELEVANCE_BATCH_SIZE", 10)
        calls: list[int] = []

        async def fake_call_llm_json(
            *, prompt: str, spec: Any
        ) -> dict[str, Any]:
            candidate_count = prompt.count("**Candidate ")
            calls.append(candidate_count)
            return {"judgments": _stub_judgments(count=candidate_count)}

        monkeypatch.setattr(relevance, "call_llm_json", fake_call_llm_json)

        ranked = _pool(25)
        result = await relevance.apply_semantic_relevance(
            ranked, research_goal="a goal", model_name="stub/model", budget=10
        )

        assert len(calls) == 3
        assert sorted(calls) == [4, 10, 10]
        assert (
            result["p25"]["retriever_version"]
            == relevance._LEXICAL_ONLY_VERSION
        )

    async def test_apply_semantic_relevance_maps_verdicts_back_by_index(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        async def fake_call_llm_json(
            *, prompt: str, spec: Any
        ) -> dict[str, Any]:
            # Reversal distinguishes candidate indices from list positions.
            return {
                "judgments": [
                    {"index": 3, "relevance": 0.3, "rationale": "third"},
                    {"index": 1, "relevance": 0.9, "rationale": "first"},
                    {"index": 2, "relevance": 0.1, "rationale": "second"},
                ]
            }

        monkeypatch.setattr(relevance, "call_llm_json", fake_call_llm_json)

        ranked = _pool(3)
        result = await relevance.apply_semantic_relevance(
            ranked, research_goal="a goal", model_name="stub/model", budget=5
        )

        assert result["p1"]["retrieval_rationale"] == "first"
        assert result["p2"]["retrieval_rationale"] == "second"
        assert result["p3"]["retrieval_rationale"] == "third"

    async def test_apply_semantic_relevance_batch_failure_degrades_like_single(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        async def failing_call_llm_json(*, prompt: str, spec: Any) -> Any:
            raise RuntimeError("provider exploded")

        monkeypatch.setattr(relevance, "call_llm_json", failing_call_llm_json)

        ranked = _pool(2)
        result = await relevance.apply_semantic_relevance(
            ranked, research_goal="a goal", model_name="stub/model", budget=5
        )

        for metadata in result.values():
            assert metadata["retrieval_rationale"] == (
                relevance._FAILED_JUDGMENT_RATIONALE
            )
            assert metadata["retriever_version"] == relevance._HYBRID_VERSION

    async def test_apply_semantic_relevance_bad_relevance_type_degrades_only_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """One malformed field must not abort sibling batches through gather."""

        async def fake_call_llm_json(
            *, prompt: str, spec: Any
        ) -> dict[str, Any]:
            return {
                "judgments": [
                    {"index": 1, "relevance": "n/a", "rationale": "bad type"},
                    {"index": 2, "relevance": 0.8, "rationale": "fine"},
                ]
            }

        monkeypatch.setattr(relevance, "call_llm_json", fake_call_llm_json)

        ranked = _pool(2)
        result = await relevance.apply_semantic_relevance(
            ranked, research_goal="a goal", model_name="stub/model", budget=5
        )

        assert result["p1"]["retrieval_rationale"] == (
            relevance._FAILED_JUDGMENT_RATIONALE
        )
        assert result["p2"]["retrieval_rationale"] == "fine"

    async def test_apply_semantic_relevance_handles_short_response_array(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        async def fake_call_llm_json(
            *, prompt: str, spec: Any
        ) -> dict[str, Any]:
            return {
                "judgments": [{"index": 1, "relevance": 0.7, "rationale": "ok"}]
            }

        monkeypatch.setattr(relevance, "call_llm_json", fake_call_llm_json)

        ranked = _pool(3)
        result = await relevance.apply_semantic_relevance(
            ranked, research_goal="a goal", model_name="stub/model", budget=5
        )

        assert result["p1"]["retrieval_rationale"] == "ok"
        assert result["p2"]["retrieval_rationale"] == (
            relevance._FAILED_JUDGMENT_RATIONALE
        )
        assert result["p3"]["retrieval_rationale"] == (
            relevance._FAILED_JUDGMENT_RATIONALE
        )

    def test_match_batch_judgments_missing_index_falls_back_to_list_order(
        self,
    ) -> None:
        judgments: list[Any] = [
            {"relevance": 0.5, "rationale": "no index"},
            {"index": 1, "relevance": 0.9, "rationale": "explicit"},
        ]
        matched = relevance._match_batch_judgments(judgments, ["p1", "p2"])
        assert matched[0]["rationale"] == "explicit"
        assert matched[1]["rationale"] == "no index"

    def test_match_batch_judgments_duplicate_index_falls_back_for_the_second(
        self,
    ) -> None:
        judgments: list[Any] = [
            {"index": 1, "relevance": 0.9, "rationale": "first claim"},
            {"index": 1, "relevance": 0.1, "rationale": "duplicate claim"},
        ]
        matched = relevance._match_batch_judgments(judgments, ["p1", "p2"])
        assert matched[0]["rationale"] == "first claim"
        assert matched[1]["rationale"] == "duplicate claim"


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
        config = SearchConfig(
            tool_registry=None,
            workflow=None,
            is_multi_source=False,
            search_tool_name="pubmed_fulltext",
            search_tool_config=None,
            source_name="pubmed",
            papers_to_read_count=3,
            is_dev_mode=False,
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
        config = SearchConfig(
            tool_registry=None,
            workflow=None,
            is_multi_source=False,
            search_tool_name="pubmed_fulltext",
            search_tool_config=None,
            source_name="pubmed",
            papers_to_read_count=3,
            is_dev_mode=False,
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
    """Fails a set number of times, then returns a payload."""

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
    """Returns the MCP server's own tool-error envelope, every call."""

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
