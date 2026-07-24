"""Tests for progressive broadening of keyword literature queries.

Literature back ends AND every term, so a query's hit count collapses as
terms are added. Measured against PubMed with one production run's own
generated queries: ``mifepristone glioblastoma`` returns 16 records, the
four-term form returns 1, and the nine-term form the run actually issued
returns 0. Nothing downstream tells "over-constrained" apart from "no such
literature", so the run assessed its claims against a pool that never
covered them.

External seams stubbed: only the MCP client's ``call_tool``; no network,
LLM, or disk I/O anywhere in this module.
"""

from typing import Any, cast

from co_scientist.agents.generation.literature_review import search
from co_scientist.agents.generation.literature_review.query_broadening import (
    broadened_queries,
)
from co_scientist.config import ToolConfig
from co_scientist.mcp_client import MCPToolClient

_NINE_TERMS = (
    "mifepristone glucocorticoid receptor antagonist glioblastoma "
    "blood brain barrier PD-L1"
)


def test_ladder_narrows_to_the_range_that_actually_returns_records() -> None:
    """The rungs are the measured recovery points, not arbitrary lengths."""
    assert broadened_queries(_NINE_TERMS) == [
        _NINE_TERMS,
        # 1 record on PubMed, where the nine-term form returns none.
        "mifepristone glucocorticoid receptor antagonist glioblastoma",
        # 2811 records; the floor still names a topic.
        "mifepristone glucocorticoid",
    ]


def test_a_query_already_short_enough_is_left_alone() -> None:
    """Two terms name a topic; one is a subject heading. Neither broadens."""
    assert broadened_queries("mifepristone glioblastoma") == [
        "mifepristone glioblastoma"
    ]
    assert broadened_queries("copper") == ["copper"]


class _QueryScriptedClient:
    """Fake MCP client returning a scripted response per exact query."""

    def __init__(self, responses: dict[str, Any]) -> None:
        """Map each exact query string to its response or exception."""
        self._responses = responses
        self.queries: list[str] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Record the query and return (or raise) its scripted outcome."""
        query = str(kwargs["query"])
        self.queries.append(query)
        outcome = self._responses[query]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _papers(*ids: str) -> dict[str, Any]:
    """A search response carrying the given paper ids."""
    return {i: {"title": i} for i in ids}


def _ctx(client: Any, errors: list[str]) -> search._SearchRunContext:
    """A run context over the shared slug for search calls."""
    return search._SearchRunContext(
        slug="slug",
        run_id="run1",
        mcp_client=cast(MCPToolClient, client),
        errors=errors,
    )


async def _search(client: Any, query: str, errors: list[str]) -> Any:
    """Run one source query through the function under test."""
    return await search._search_source_for_query(
        query,
        _ctx(client, errors),
        ToolConfig(server="s", mcp_tool_name="search_pubmed"),
        "pubmed",
        papers_per_query=4,
    )


async def test_an_empty_query_is_retried_in_broader_form() -> None:
    """The over-constrained query returns nothing; the broader one lands."""
    ladder = broadened_queries(_NINE_TERMS)
    client = _QueryScriptedClient(
        {
            ladder[0]: _papers(),
            ladder[1]: _papers("p1", "p2"),
        }
    )
    errors: list[str] = []

    result = await _search(client, _NINE_TERMS, errors)

    assert sorted(result) == ["p1", "p2"]
    assert client.queries == [ladder[0], ladder[1]]
    # Zero results is not an error: nothing broke, the query was too narrow.
    assert errors == []


async def test_broadening_walks_to_the_floor_when_it_has_to() -> None:
    """Some queries only return records at the shortest form."""
    ladder = broadened_queries(_NINE_TERMS)
    client = _QueryScriptedClient(
        {
            ladder[0]: _papers(),
            ladder[1]: _papers(),
            ladder[2]: _papers("p9"),
        }
    )

    result = await _search(client, _NINE_TERMS, [])

    assert list(result) == ["p9"]
    assert client.queries == ladder


async def test_a_query_that_returns_records_is_never_broadened() -> None:
    """Broadening is a recovery path, not a second search on every query."""
    client = _QueryScriptedClient({_NINE_TERMS: _papers("p1")})

    result = await _search(client, _NINE_TERMS, [])

    assert list(result) == ["p1"]
    assert client.queries == [_NINE_TERMS]


async def test_a_failed_search_is_not_retried_broader() -> None:
    """The query was not what failed, so a shorter one fails the same way.

    Retrying would multiply an outage across every query in the run rather
    than recovering anything.
    """
    client = _QueryScriptedClient({_NINE_TERMS: RuntimeError("backend down")})
    errors: list[str] = []

    result = await _search(client, _NINE_TERMS, errors)

    assert result == {}
    # _call_search_tool retries a transient failure itself, but every attempt
    # is the same query: the failure never advances the ladder.
    assert set(client.queries) == {_NINE_TERMS}
    assert errors and "backend down" in errors[0]
