"""Tests for the transient-failure retry around one search tool call.

A search source fails transiently for reasons that take seconds to clear --
an index throttling a burst of concurrent queries, an MCP session
reconnecting, an upstream returning a status page instead of JSON. The
budget used to be a single retry a quarter-second later, which re-asks while
the cause is still in force and then drops the whole query; the run then
reaches its claim gate with a pool that never covered the topic.

External seams stubbed: only the MCP client's ``call_tool`` and
``asyncio.sleep``; no network, LLM, or disk I/O anywhere in this module.
"""

import asyncio
import json
from typing import Any, cast

import pytest

from co_scientist.agents.generation.literature_review import search
from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.response_parser import parse_mcp_result


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


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record backoff delays instead of waiting them out."""
    slept: list[float] = []

    async def _record(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _record)
    return slept


@pytest.mark.asyncio
async def test_a_source_survives_more_than_one_transient_failure() -> None:
    """Two failures in a row must not cost the query.

    The old budget was one retry, so the second failure raised and the
    caller dropped the query entirely.
    """
    client = _FlakyClient(failures=2)

    result = await search._call_search_tool(
        cast(MCPToolClient, client), "search_pubmed", {}
    )

    assert result == {"papers": []}
    assert client.calls == 3


@pytest.mark.asyncio
async def test_exhausted_retries_still_raise_to_the_caller() -> None:
    """A source that never recovers surfaces its failure, not an empty hit.

    The caller distinguishes "search broke" from "no results"; swallowing
    the exhausted case here would erase that difference.
    """
    client = _FlakyClient(failures=search._SEARCH_ATTEMPTS)

    with pytest.raises(RuntimeError, match="throttling"):
        await search._call_search_tool(
            cast(MCPToolClient, client), "search_pubmed", {}
        )

    assert client.calls == search._SEARCH_ATTEMPTS


@pytest.mark.asyncio
async def test_backoff_grows_and_is_jittered(
    _no_real_sleep: list[float],
) -> None:
    """Delays escalate, and no two runs share a schedule.

    A fixed schedule releases every throttled caller of a concurrent wave at
    the same moment, reproducing the burst that caused the throttling.
    """
    client = _FlakyClient(failures=search._SEARCH_ATTEMPTS - 1)
    await search._call_search_tool(
        cast(MCPToolClient, client), "search_pubmed", {}
    )
    first = list(_no_real_sleep)
    _no_real_sleep.clear()

    client2 = _FlakyClient(failures=search._SEARCH_ATTEMPTS - 1)
    await search._call_search_tool(
        cast(MCPToolClient, client2), "search_pubmed", {}
    )

    assert len(first) == search._SEARCH_ATTEMPTS - 1
    assert first == sorted(first)
    assert sum(first) > 4 * 0.25  # comfortably past the old single 0.25s
    assert first != _no_real_sleep


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
    """The decode failure names what came back, not just that it was not JSON.

    "Expecting value: line 1 column 1 (char 0)" reports the one thing
    already known, and cannot tell a gateway error page from a throttling
    notice from an empty body -- which need different fixes.
    """
    with pytest.raises(json.JSONDecodeError) as caught:
        parse_mcp_result(payload)

    assert expected in str(caught.value)
