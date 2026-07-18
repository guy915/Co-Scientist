"""Tests for per-call MCP tool logging."""

import asyncio
import inspect
import logging

import pytest
from mcp_server.tool_logging import with_call_logging


def test_logs_name_arguments_and_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def search(query: str, limit: int = 5) -> str:
        return '{"a": 1, "b": 2}'

    with caplog.at_level(logging.INFO):
        with_call_logging(search, "search")("kinases", limit=3)

    record = caplog.text
    assert "tool search(" in record
    assert "'kinases'" in record and "limit=3" in record
    assert "2 items" in record
    assert "ms" in record


def test_distinguishes_empty_from_populated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An empty result is the signature of a degraded call, so name it.

    Every tool here returns {} on a failed request, a missing key, and a
    genuine no-match alike, so the log line is the only way to tell that a
    call happened at all.
    """

    def nothing(q: str) -> str:
        return "{}"

    with caplog.at_level(logging.INFO):
        with_call_logging(nothing, "nothing")("zzz")
    assert "-> empty" in caplog.text


def test_logs_dict_returning_tools(caplog: pytest.LogCaptureFixture) -> None:
    """Some tools return dicts rather than JSON strings."""

    def as_dict(q: str) -> dict[str, int]:
        return {"x": 1}

    with caplog.at_level(logging.INFO):
        with_call_logging(as_dict, "as_dict")("q")
    assert "1 item" in caplog.text


def test_logs_and_reraises_failures(caplog: pytest.LogCaptureFixture) -> None:
    def broken(q: str) -> str:
        raise RuntimeError("upstream down")

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
        with_call_logging(broken, "broken")("q")
    assert "raised RuntimeError" in caplog.text
    # The traceback survives, since a raise is unexpected for these tools.
    assert "upstream down" in caplog.text


def test_wraps_async_tools(caplog: pytest.LogCaptureFixture) -> None:
    """Most tools here are async, so the wrapper must stay awaitable."""

    async def fetch(q: str) -> str:
        return '{"a": 1}'

    wrapped = with_call_logging(fetch, "fetch")
    assert inspect.iscoroutinefunction(wrapped)
    with caplog.at_level(logging.INFO):
        assert asyncio.run(wrapped("q")) == '{"a": 1}'
    assert "tool fetch(" in caplog.text


def test_preserves_the_signature_fastmcp_advertises() -> None:
    """FastMCP builds each tool's parameter schema from its signature.

    A bare *args/**kwargs wrapper would erase every parameter from the schema
    the agent sees, leaving tools that look argument-less and cannot be
    called correctly. This is the property that would break silently.
    """

    def search(query: str, max_passages: int = 5) -> str:
        """Docstring feeds the tool description."""
        return "{}"

    wrapped = with_call_logging(search, "search")
    assert inspect.signature(wrapped) == inspect.signature(search)
    assert list(inspect.signature(wrapped).parameters) == [
        "query",
        "max_passages",
    ]
    assert wrapped.__name__ == "search"
    assert wrapped.__doc__ == search.__doc__
    assert wrapped.__annotations__ == search.__annotations__


def test_truncates_a_long_argument(caplog: pytest.LogCaptureFixture) -> None:
    def search(query: str) -> str:
        return "{}"

    with caplog.at_level(logging.INFO):
        with_call_logging(search, "search")("x" * 500)
    assert "..." in caplog.text
    # The line stays readable rather than dumping the whole argument.
    assert len(max(caplog.text.split("\n"), key=len)) < 400


def test_returns_the_result_unchanged() -> None:
    """Logging is an observer; it must not alter what the agent receives."""

    def tool(q: str) -> str:
        return '{"untouched": true}'

    assert with_call_logging(tool, "tool")("q") == '{"untouched": true}'
