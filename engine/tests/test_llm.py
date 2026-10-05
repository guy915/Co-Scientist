from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast

import pytest

from co_scientist.llm import (
    CompletionSpec,
    call_llm_json,
    complete_request,
    indexed_prompt_name,
    scoped_telemetry,
)
from co_scientist.llm.structured.validate import attempt_json_repair
from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.provider import MCPToolProvider
from tests._llm_fake import (
    disable_llm_cache,
    install_fake_backend,
    make_completion,
    make_message,
    patch_acompletion,
)
from tests._mcp import make_tool_call

_FENCED = '```json\n{"a": 1}\n```'
_LATEX = r'{"experiment": "use GFP-Ub\(^{G76V}\) reporter"}'


@pytest.mark.parametrize(
    ("text", "major", "expected"),
    [
        ('{"a": 1, "b": "x"}', False, ({"a": 1, "b": "x"}, False)),
        ('  {"a": 1}  ', False, ({"a": 1}, False)),
        ("{}", True, ({}, False)),
        ("[1, 2, 3]", False, ([1, 2, 3], False)),
        ("[]", False, (None, False)),
        ('{"a": 1,}', False, ({"a": 1}, False)),
        ('{"a": [1, 2,]}', False, ({"a": [1, 2]}, False)),
        (_FENCED, False, (None, False)),
        (_FENCED, True, ({"a": 1}, True)),
        ("{'a': 1}", True, (None, False)),
        ('{"a": 1, "b": 2', False, (None, False)),
        ('{"a": 1, "b": 2', True, ({"a": 1, "b": 2}, True)),
        ('{"a": "hello', True, ({"a": "hello"}, True)),
        ('{"items": ["x", "y', True, ({"items": ["x", "y"]}, True)),
        ('{"a": {"b": 1', True, ({"a": {"b": 1}}, True)),
        ("[1, 2, 3", True, ([1, 2, 3], True)),
        ('Here is: {"a": 1} thanks', False, (None, False)),
        ('Here is: {"a": 1} thanks', True, ({"a": 1}, True)),
        ("this is not json at all", True, (None, False)),
        ("   ", True, (None, False)),
        (
            _LATEX,
            False,
            ({"experiment": r"use GFP-Ub\(^{G76V}\) reporter"}, False),
        ),
        (
            r'{"a": "x\(y", "b": 1,}',
            False,
            ({"a": r"x\(y", "b": 1}, False),
        ),
        (
            r'{"a": "line\n\t\"q\"\\done"}',
            False,
            ({"a": 'line\n\t"q"\\done'}, False),
        ),
    ],
)
def test_json_repair_fixes_minor_flaws_and_gates_major_ones(
    text: str, major: bool, expected: tuple[Any, bool]
) -> None:
    assert attempt_json_repair(text, allow_major_repairs=major) == expected


@pytest.mark.parametrize(
    ("schema_name", "degraded"),
    [
        ("proximity_analysis", True),
        ("hypothesis_evolution", True),
        ("hypothesis_batch_review", True),
        ("hypothesis_generation", False),
        ("supervisor_guidance", False),
        (None, False),
    ],
)
async def test_only_an_enhancement_node_degrades_when_every_retry_fails(
    monkeypatch: pytest.MonkeyPatch, schema_name: str | None, degraded: bool
) -> None:
    disable_llm_cache(monkeypatch)
    patch_acompletion(
        monkeypatch, [make_completion(make_message("not json"))] * 4
    )
    schema = {"name": schema_name, "type": "object"} if schema_name else None
    spec = CompletionSpec(model_name="test-model", json_schema=schema)

    if not degraded:
        with pytest.raises(json.JSONDecodeError):
            await call_llm_json("a prompt", spec, max_attempts=2)
        return
    first = await call_llm_json("a prompt", spec, max_attempts=2)
    first.setdefault("reviews", []).append("dirty")
    second = await call_llm_json("a prompt", spec, max_attempts=2)
    assert "dirty" not in second.get("reviews", []), "each caller gets a copy"


@pytest.mark.parametrize(
    ("stem", "index", "expected"),
    [("evolve", 3, "evolve_3"), ("m", 0, "m_0"), ("review", None, "review")],
)
def test_a_prompt_name_carries_its_index_only_when_it_has_one(
    stem: str, index: int | None, expected: str
) -> None:
    assert indexed_prompt_name(stem, index) == expected


def test_importing_a_foundation_module_first_does_not_cycle() -> None:
    """Only a fresh interpreter exposes cycles involving a half-initialized
    cache module."""
    result = subprocess.run(
        [sys.executable, "-c", "import co_scientist.cache"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


class FakeMCPClient:
    def __init__(self, tools: dict[str, Any] | None = None) -> None:
        self._tools = tools or {}
        self.get_tools_calls: list[list[str] | None] = []
        self.executed: list[Any] = []

    def get_tools(
        self, whitelist: list[str] | None = None
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        self.get_tools_calls.append(whitelist)
        selected = {
            name: obj
            for name, obj in self._tools.items()
            if whitelist is None or name in whitelist
        }
        schemas = [
            {"type": "function", "function": {"name": name}}
            for name in selected
        ]
        return selected, schemas

    async def execute_tool_call(self, tool_call: Any) -> dict[str, Any]:
        self.executed.append(tool_call)
        return {
            "role": "tool",
            "name": tool_call.function.name,
            "tool_call_id": tool_call.id,
            "content": "mcp-result",
        }


class FailingMCPClient(FakeMCPClient):
    async def execute_tool_call(self, tool_call: Any) -> dict[str, Any]:
        raise RuntimeError(f"server unavailable for {tool_call.function.name}")


def _provider(fake: FakeMCPClient) -> MCPToolProvider:
    provider = MCPToolProvider(mcp_client=cast(MCPToolClient, fake))
    provider.get_tools(mcp_whitelist=["pubmed_search"])
    return provider


@pytest.mark.parametrize(
    ("whitelist", "names"),
    [
        (None, {"pubmed_search", "other"}),
        (["pubmed_search"], {"pubmed_search"}),
        ([], set()),
    ],
)
def test_the_tool_whitelist_filters_what_the_client_offers(
    whitelist: list[str] | None, names: set[str]
) -> None:
    fake = FakeMCPClient({"pubmed_search": object(), "other": object()})

    tools, schemas = MCPToolProvider(
        mcp_client=cast(MCPToolClient, fake)
    ).get_tools(mcp_whitelist=whitelist)

    assert set(tools) == names
    assert {s["function"]["name"] for s in schemas} == names
    assert fake.get_tools_calls == [whitelist]


async def test_a_known_tool_call_is_delegated_and_counted() -> None:
    fake = FakeMCPClient({"pubmed_search": object()})
    provider = _provider(fake)
    executor, counts = provider.tracked_executor("Draft")
    call = make_tool_call(
        "pubmed_search", json.dumps({"query": "cancer"}), call_id="call-mcp"
    )

    result = await executor(call)
    await executor(make_tool_call("pubmed_search", "{}"))

    assert (result["name"], result["tool_call_id"]) == (
        "pubmed_search",
        "call-mcp",
    )
    assert result["content"] == "mcp-result"
    assert counts == {"pubmed_search": 2}
    assert fake.executed[0] is call


async def test_an_unknown_tool_or_failing_client_becomes_an_error_result() -> (
    None
):
    unknown = await _provider(FakeMCPClient()).execute_tool_call(
        make_tool_call("nope_tool", "{}", call_id="call-x")
    )
    assert unknown["role"] == "tool"
    assert unknown["tool_call_id"] == "call-x"
    assert json.loads(unknown["content"])["error"] == "unknown tool: nope_tool"

    failing = await _provider(
        FailingMCPClient({"pubmed_search": object()})
    ).execute_tool_call(make_tool_call("pubmed_search", "{}"))
    error = json.loads(failing["content"])["error"]
    assert "tool execution failed" in error
    assert "server unavailable" in error

    provider = _provider(FakeMCPClient({"pubmed_search": object()}))
    provider.mcp_client = None
    unconfigured = await provider.execute_tool_call(
        make_tool_call("pubmed_search", "{}")
    )
    assert "MCP client not configured" in unconfigured["content"]


async def test_usage_is_recorded_once_after_the_stream_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final = SimpleNamespace(
        model="gpt-4o-mini",
        choices=[],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3),
    )

    async def chunks() -> AsyncIterator[Any]:
        yield SimpleNamespace(choices=[], usage=None)
        yield final

    async def provider(**kwargs: Any) -> Any:
        return chunks()

    install_fake_backend(monkeypatch, provider)
    with scoped_telemetry("app_stream") as telemetry:
        response = await complete_request(
            {"model": "gpt-4o-mini", "stream": True},
            "gpt-4o-mini",
            byok=False,
            timeout_seconds=1,
        )
        assert telemetry.snapshot() == {}
    assert len([chunk async for chunk in response]) == 2
    await response.aclose()
    usage = telemetry.snapshot()["app_stream::gpt-4o-mini"]
    assert usage["calls"] == 1
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 3
    assert usage["reported_usage_calls"] == 1
    assert usage["errors"] == {}


async def test_partial_stream_close_records_unknown_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = asyncio.Event()

    async def chunks() -> AsyncIterator[Any]:
        try:
            yield "reasoning"
            await asyncio.sleep(3600)
        finally:
            closed.set()

    async def provider(**kwargs: Any) -> Any:
        return chunks()

    install_fake_backend(monkeypatch, provider)
    with scoped_telemetry("cancelled") as telemetry:
        response = await complete_request(
            {"model": "gpt-4o-mini", "stream": True},
            "gpt-4o-mini",
            byok=False,
            timeout_seconds=1,
        )
        assert await anext(response) == "reasoning"
        await response.aclose()
    assert closed.is_set()
    usage = telemetry.snapshot()["cancelled::gpt-4o-mini"]
    assert usage["calls"] == 1
    assert usage["reported_usage_calls"] == 0
    assert usage["errors"] == {"CancelledError": 1}
