"""Offline contracts for llm."""

from __future__ import annotations

import asyncio
import importlib
import json
import subprocess
import sys
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast

import pytest
from jsonschema.exceptions import ValidationError

import co_scientist.llm as llm
from co_scientist.llm import (
    complete_request,
    indexed_prompt_name,
    scoped_telemetry,
)
from co_scientist.llm.structured.validate import (
    attempt_json_repair,
    get_fallback_response,
    validate_json_schema,
)
from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.provider import MCPToolProvider
from tests._llm_fake import install_fake_backend
from tests._mcp import make_tool_call

# --- attempt_json_repair: clean parses (no repair) -------------------------


def test_valid_object_parsed_without_repair() -> None:
    """A valid JSON object parses directly with ``was_repaired`` False."""
    assert attempt_json_repair('{"a": 1, "b": "x"}') == (
        {"a": 1, "b": "x"},
        False,
    )


def test_valid_object_with_surrounding_whitespace() -> None:
    """Leading/trailing whitespace around a valid object is tolerated."""
    assert attempt_json_repair('  {"a": 1}  ') == ({"a": 1}, False)


def test_empty_object_returned_as_is() -> None:
    """An empty object ``{}`` is returned by the initial parse, not repaired.

    The falsy-result guard (``if result:``) only runs inside the repair
    loops, so the initial ``isinstance(result, dict)`` branch returns ``{}``
    verbatim with ``was_repaired`` False.
    """
    assert attempt_json_repair("{}") == ({}, False)


def test_empty_object_with_major_repairs_still_returned_as_is() -> None:
    """``{}`` short-circuits in the initial parse even when major is allowed."""
    assert attempt_json_repair("{}", allow_major_repairs=True) == ({}, False)


def test_valid_array_returns_list_not_dict() -> None:
    """A valid JSON array is returned as a list, despite the dict-typed hint.

    The initial parse only returns when the result is a dict, so the array
    falls through to the (trailing-comma) minor-repair strategy, which
    re-parses it and returns the truthy list with ``was_repaired`` False.
    This documents that the ``tuple[dict | None, bool]`` annotation does not
    hold for array inputs.
    """
    parsed, repaired = attempt_json_repair("[1, 2, 3]")
    assert isinstance(parsed, list)
    assert parsed == [1, 2, 3]
    assert repaired is False


def test_empty_array_returns_none() -> None:
    """An empty array is not returned: the empty list is falsy and skipped."""
    assert attempt_json_repair("[]") == (None, False)


# --- attempt_json_repair: minor repairs (trailing commas) ------------------


def test_trailing_comma_in_object_is_minor_repair() -> None:
    """A trailing comma before ``}`` is fixed and reported as NOT major.

    Trailing-comma removal is a minor repair, so ``was_repaired`` is False
    even though the input was malformed.
    """
    assert attempt_json_repair('{"a": 1,}') == ({"a": 1}, False)


def test_trailing_comma_in_nested_array_is_minor_repair() -> None:
    """A trailing comma inside a nested array is fixed as a minor repair."""
    assert attempt_json_repair('{"a": [1, 2,]}') == ({"a": [1, 2]}, False)


# --- attempt_json_repair: markdown fences are NOT handled here -------------


def test_markdown_json_fence_is_not_unwrapped() -> None:
    r"""A ```json fenced block is NOT stripped by ``attempt_json_repair``.

    Despite the task brief, fence stripping lives in ``call_llm_json`` (a
    network-backed caller), not in this pure function. With only minor
    repairs the fenced payload is unparseable and returns ``(None, False)``.
    Under major repairs the inner object is still recovered, but via the
    generic ``\{.*\}`` regex-extraction strategy (treated as a major
    repair), NOT via any fence-aware logic.
    """
    fenced = '```json\n{"a": 1}\n```'
    assert attempt_json_repair(fenced) == (None, False)
    assert attempt_json_repair(fenced, allow_major_repairs=True) == (
        {"a": 1},
        True,
    )


# --- attempt_json_repair: single quotes are NOT repaired ------------------


def test_single_quoted_json_is_not_repaired() -> None:
    """Single-quoted (Python-style) JSON is not repaired by this function.

    Contrary to the task brief, there is no single-quote-to-double-quote
    strategy; the input stays unparseable in both modes.
    """
    assert attempt_json_repair("{'a': 1}") == (None, False)
    assert attempt_json_repair("{'a': 1}", allow_major_repairs=True) == (
        None,
        False,
    )


# --- attempt_json_repair: the major-repair gate ----------------------------


def test_truncated_object_repaired_only_with_major_repairs() -> None:
    """Unbalanced/truncated JSON is closed only when major repairs are on.

    With ``allow_major_repairs=True`` the missing ``}`` is added and the
    object parses, with ``was_repaired`` True. With the flag off the gate
    holds and nothing is returned.
    """
    truncated = '{"a": 1, "b": 2'
    assert attempt_json_repair(truncated, allow_major_repairs=True) == (
        {"a": 1, "b": 2},
        True,
    )
    assert attempt_json_repair(truncated, allow_major_repairs=False) == (
        None,
        False,
    )


def test_truncated_object_default_does_not_major_repair() -> None:
    """The default (no kwarg) does not perform major repairs."""
    assert attempt_json_repair('{"a": 1, "b": 2') == (None, False)


def test_unterminated_string_value_closed_with_major_repairs() -> None:
    """An unterminated string value is closed under major repairs."""
    assert attempt_json_repair('{"a": "hello', allow_major_repairs=True) == (
        {"a": "hello"},
        True,
    )


def test_truncated_array_value_closed_with_major_repairs() -> None:
    """A truncated array value is closed (string + bracket) under major."""
    assert attempt_json_repair(
        '{"items": ["x", "y', allow_major_repairs=True
    ) == ({"items": ["x", "y"]}, True)


def test_nested_truncated_object_closed_with_major_repairs() -> None:
    """A truncated nested object gets both braces added under major repairs."""
    assert attempt_json_repair('{"a": {"b": 1', allow_major_repairs=True) == (
        {"a": {"b": 1}},
        True,
    )


def test_truncated_root_array_closed_with_major_repairs() -> None:
    """A truncated top-level array is closed and returned as a list (major)."""
    parsed, repaired = attempt_json_repair("[1, 2, 3", allow_major_repairs=True)
    assert isinstance(parsed, list)
    assert parsed == [1, 2, 3]
    assert repaired is True


def test_json_object_embedded_in_prose_extracted_only_with_major() -> None:
    """An object embedded in surrounding prose is extracted only under major.

    The regex-extraction strategy (a major repair) pulls the first ``{...}``
    out of the text; without major repairs the input is left unparsed.
    """
    text = 'Here is the answer: {"a": 1} thanks'
    assert attempt_json_repair(text, allow_major_repairs=True) == (
        {"a": 1},
        True,
    )
    assert attempt_json_repair(text, allow_major_repairs=False) == (None, False)


# --- attempt_json_repair: unrepairable input -------------------------------


def test_plain_garbage_returns_none() -> None:
    """Non-JSON prose is unrepairable and returns ``(None, False)``."""
    assert attempt_json_repair("this is not json at all") == (None, False)
    assert attempt_json_repair(
        "this is not json at all", allow_major_repairs=True
    ) == (None, False)


def test_empty_string_without_major_repairs_returns_none() -> None:
    """An empty string with only minor repairs returns ``(None, False)``."""
    assert attempt_json_repair("") == (None, False)


def test_empty_string_with_major_repairs_returns_none() -> None:
    """Empty input under major repairs returns no value rather than crashing.

    Regression guard: ``close_truncated_json`` short-circuits on an empty (or
    whitespace-only) string instead of indexing ``stripped[-1]``, so the
    repair honors the documented ``(None, ...)`` contract.
    """
    parsed, _ = attempt_json_repair("", allow_major_repairs=True)
    assert parsed is None


def test_whitespace_only_with_major_repairs_returns_none() -> None:
    """Whitespace-only input also returns no value after the empty guard."""
    parsed, _ = attempt_json_repair("   ", allow_major_repairs=True)
    assert parsed is None


# --- validate_json_schema --------------------------------------------------

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
}


def test_validate_json_schema_passes_for_valid_instance() -> None:
    """A conforming instance validates and returns None (no raise)."""
    validate_json_schema({"a": 1}, _SCHEMA)  # no exception == valid


def test_validate_json_schema_none_schema_skips_validation() -> None:
    """A ``None`` schema skips validation entirely (returns None)."""
    validate_json_schema({"anything": True}, None)  # no exception == valid


def test_validate_json_schema_unwraps_nested_schema_key() -> None:
    """A schema wrapped under a ``schema`` key is unwrapped before use."""
    nested = {"name": "node", "schema": _SCHEMA}
    validate_json_schema({"a": 5}, nested)  # no exception == valid


def test_validate_json_schema_raises_on_type_mismatch() -> None:
    """A type mismatch against the schema raises ``ValidationError``."""
    with pytest.raises(ValidationError):
        validate_json_schema({"a": "not an int"}, _SCHEMA)


def test_validate_json_schema_raises_on_missing_required() -> None:
    """A missing required property raises ``ValidationError``."""
    with pytest.raises(ValidationError):
        validate_json_schema({}, _SCHEMA)


# --- get_fallback_response -------------------------------------------------


def test_fallback_none_schema_returns_none() -> None:
    """A ``None`` schema yields no fallback."""
    assert get_fallback_response(None) is None


def test_fallback_for_proximity_node() -> None:
    """The proximity node gets a concrete skip-deduplication fallback dict."""
    fallback = get_fallback_response({"name": "proximity_analysis"})
    assert fallback == {
        "similarity_clusters": [],
        "diversity_assessment": "Analysis failed - skipping deduplication",
        "redundancy_assessment": "Analysis failed - skipping deduplication",
    }


def test_fallback_for_critical_node_returns_none() -> None:
    """A critical (non-proximity) node has no fallback."""
    assert get_fallback_response({"name": "generate_hypotheses"}) is None


def test_fallback_schema_without_name_returns_none() -> None:
    """A schema with no ``name`` field has no fallback."""
    assert get_fallback_response({}) is None


# --- attempt_json_repair: invalid backslash escapes (LaTeX/math) -----------


def test_invalid_latex_escape_is_minor_repaired() -> None:
    r"""LaTeX-style ``\(...\)`` in a string value is repaired (minor).

    This is the real-world failure that aborted a run: DeepSeek emitted
    ``GFP-Ub\(^{G76V}\)`` inside a JSON string, and ``\(`` is not a valid JSON
    escape. The repair doubles the lone backslashes so the literal text
    survives, and it succeeds WITHOUT major repairs.
    """
    raw = r'{"experiment": "use GFP-Ub\(^{G76V}\) reporter"}'
    parsed, was_major = attempt_json_repair(raw)
    assert parsed == {"experiment": r"use GFP-Ub\(^{G76V}\) reporter"}
    assert was_major is False


def test_invalid_escape_with_trailing_comma_repaired() -> None:
    """Combined invalid escape + trailing comma is still a minor repair."""
    raw = r'{"a": "x\(y", "b": 1,}'
    parsed, was_major = attempt_json_repair(raw)
    assert parsed == {"a": r"x\(y", "b": 1}
    assert was_major is False


def test_valid_escapes_are_left_intact() -> None:
    """Legitimate JSON escapes are not double-escaped by the repair."""
    # Valid as-is, so it parses without any repair.
    assert attempt_json_repair(r'{"a": "line\n\t\"q\"\\done"}') == (
        {"a": 'line\n\t"q"\\done'},
        False,
    )


# --- get_fallback_response: enhancement nodes degrade, foundational fail ---


def test_enhancement_nodes_get_a_fallback() -> None:
    """Every post-generation enhancement node degrades instead of aborting."""
    for name in (
        "proximity_analysis",
        "hypothesis_evolution",
        "hypothesis_review",
        "hypothesis_batch_review",
        "reflection_observations",
        "meta_review",
        "deep_verification",
        "research_overview",
    ):
        assert get_fallback_response({"name": name}) is not None, name


def test_foundational_nodes_have_no_fallback() -> None:
    """Foundational nodes fail loud (no fallback) -- no hypotheses, no run."""
    for name in (
        "hypothesis_generation",
        "hypothesis_draft",
        "supervisor_guidance",
        "ranking_judgment",
    ):
        assert get_fallback_response({"name": name}) is None, name


def test_evolution_fallback_is_empty_dict_keeps_original() -> None:
    """Evolution's empty fallback routes the node to its keep-original path."""
    assert get_fallback_response({"name": "hypothesis_evolution"}) == {}


def test_batch_review_fallback_has_empty_reviews() -> None:
    """Batch review degrades to no rows; the node fills 'Review unavailable'."""
    assert get_fallback_response({"name": "hypothesis_batch_review"}) == {
        "reviews": []
    }


def test_fallback_returns_independent_copy() -> None:
    """Mutating a returned fallback must not corrupt the shared template."""
    first = get_fallback_response({"name": "hypothesis_batch_review"})
    assert first is not None
    first["reviews"].append("dirty")
    second = get_fallback_response({"name": "hypothesis_batch_review"})
    assert second == {"reviews": []}


def test_every_exported_name_resolves_to_a_defining_module() -> None:
    """``__all__`` and the lazy table agree, and each name really loads."""
    assert sorted(llm.__all__) == sorted(llm._EXPORTS)
    for name, module in llm._EXPORTS.items():
        assert module.startswith("co_scientist.llm."), name
        defined_in = importlib.import_module(module)
        assert getattr(llm, name) is getattr(defined_in, name), name


def test_the_interface_keeps_litellm_as_the_patch_seam() -> None:
    """Tests patch ``co_scientist.llm.litellm.acompletion`` by string path."""
    import litellm

    assert llm.litellm is litellm


def test_a_name_outside_the_interface_is_an_attribute_error() -> None:
    """Internals stay importable only from where they are defined."""
    with pytest.raises(AttributeError, match="_call_llm_single_attempt"):
        getattr(llm, "_call_llm_single_attempt")  # noqa: B009


def test_importing_a_foundation_module_first_does_not_cycle() -> None:
    """``cache`` reads ``llm`` names while ``llm`` itself imports ``cache``.

    Run in a fresh interpreter because the cycle only exists on a cold
    import: an interface that imported its entry points eagerly would find
    ``co_scientist.cache`` half-initialised and fail here.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import co_scientist.cache"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# --- indexed_prompt_name -----------------------------------------------------


def test_indexed_prompt_name_appends_index_when_given() -> None:
    """A given index is appended to the stem with an underscore."""
    assert indexed_prompt_name("evolve", 3) == "evolve_3"


def test_indexed_prompt_name_appends_zero_index() -> None:
    """Index 0 is still appended -- the check is "is not None", not truthy."""
    assert indexed_prompt_name("ranking_matchup", 0) == "ranking_matchup_0"


def test_indexed_prompt_name_bare_stem_when_index_is_none() -> None:
    """A None index yields the bare stem, with no trailing underscore."""
    assert indexed_prompt_name("review_individual", None) == "review_individual"


class FakeMCPClient:
    """Minimal stand-in for ``MCPToolClient`` used by the provider.

    Records the whitelist passed to ``get_tools`` and the tool calls routed to
    ``execute_tool_call`` so tests can assert routing without a real MCP server.
    """

    def __init__(self, tools: dict[str, Any] | None = None) -> None:
        """Initialize the fake with an optional name -> tool-object mapping."""
        self._tools = tools or {}
        self.get_tools_calls: list[list[str] | None] = []
        self.executed: list[Any] = []

    def get_tools(
        self,
        whitelist: list[str] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Return filtered (tools_dict, openai_tools) like the real client."""
        self.get_tools_calls.append(whitelist)
        if whitelist is None:
            selected = dict(self._tools)
        else:
            selected = {
                name: obj
                for name, obj in self._tools.items()
                if name in whitelist
            }
        openai_tools = [
            {
                "type": "function",
                "function": {"name": name},
            }
            for name in selected
        ]
        return selected, openai_tools

    async def execute_tool_call(self, tool_call: Any) -> dict[str, Any]:
        """Record the call and return a sentinel MCP tool-response message."""
        self.executed.append(tool_call)
        return {
            "role": "tool",
            "name": tool_call.function.name,
            "tool_call_id": tool_call.id,
            "content": "mcp-result",
        }


class FailingMCPClient(FakeMCPClient):
    """Fake MCP client whose executor always raises."""

    async def execute_tool_call(self, tool_call: Any) -> dict[str, Any]:
        """Raise to simulate a tool execution failure."""
        raise RuntimeError(f"server unavailable for {tool_call.function.name}")


def _make_provider(fake: FakeMCPClient) -> MCPToolProvider:
    """Build a provider around a fake client typed as MCPToolClient."""
    return MCPToolProvider(mcp_client=cast(MCPToolClient, fake))


# --- get_tools: whitelisting ------------------------------------------------


def test_get_tools_whitelist_filters_to_named_tool() -> None:
    """A whitelist returns only the named tool in dict and schemas."""
    fake = FakeMCPClient(tools={"pubmed_search": object(), "other": object()})
    provider = _make_provider(fake)
    tools_dict, openai_tools = provider.get_tools(
        mcp_whitelist=["pubmed_search"]
    )

    assert set(tools_dict.keys()) == {"pubmed_search"}
    schema_names = {t["function"]["name"] for t in openai_tools}
    assert schema_names == {"pubmed_search"}


def test_get_tools_no_whitelist_yields_all_tools() -> None:
    """Omitting the whitelist (None) exposes every tool the client offers."""
    fake = FakeMCPClient(tools={"pubmed_search": object(), "other": object()})
    provider = _make_provider(fake)
    tools_dict, openai_tools = provider.get_tools()

    assert set(tools_dict.keys()) == {"pubmed_search", "other"}
    schema_names = {t["function"]["name"] for t in openai_tools}
    assert schema_names == {"pubmed_search", "other"}
    assert fake.get_tools_calls == [None]


def test_get_tools_empty_whitelist_adds_no_tools() -> None:
    """An empty whitelist still calls the client but filters everything out."""
    fake = FakeMCPClient(tools={"pubmed_search": object()})
    provider = _make_provider(fake)
    tools_dict, _ = provider.get_tools(mcp_whitelist=[])

    assert fake.get_tools_calls == [[]]
    assert tools_dict == {}


def test_get_tools_whitelist_forwarded_to_client() -> None:
    """The whitelist is forwarded verbatim to the MCP client."""
    fake = FakeMCPClient(tools={"pubmed_search": object(), "other": object()})
    provider = _make_provider(fake)
    provider.get_tools(mcp_whitelist=["pubmed_search"])

    assert fake.get_tools_calls == [["pubmed_search"]]


# --- execute_tool_call ------------------------------------------------------


async def test_execute_delegates_known_tool_to_client() -> None:
    """A known tool call is delegated to the MCP client's executor."""
    fake = FakeMCPClient(tools={"pubmed_search": object()})
    provider = _make_provider(fake)
    provider.get_tools(mcp_whitelist=["pubmed_search"])

    tool_call = make_tool_call(
        "pubmed_search", json.dumps({"query": "cancer"}), call_id="call-mcp"
    )
    result = await provider.execute_tool_call(tool_call)

    assert fake.executed == [tool_call]
    assert result["name"] == "pubmed_search"
    assert result["tool_call_id"] == "call-mcp"
    assert result["content"] == "mcp-result"


async def test_execute_unknown_tool_returns_error_response() -> None:
    """An unlisted tool name yields an error tool-response, not a raise."""
    provider = _make_provider(FakeMCPClient())
    # No get_tools call, so no tool names are tracked.
    tool_call = make_tool_call("nope_tool", "{}", call_id="call-x")
    result = await provider.execute_tool_call(tool_call)

    assert result["role"] == "tool"
    assert result["name"] == "nope_tool"
    assert result["tool_call_id"] == "call-x"
    payload = json.loads(result["content"])
    assert payload["error"] == "unknown tool: nope_tool"


async def test_execute_client_failure_returns_error_response() -> None:
    """An exception from the MCP client surfaces as an error response."""
    fake = FailingMCPClient(tools={"pubmed_search": object()})
    provider = _make_provider(fake)
    provider.get_tools(mcp_whitelist=["pubmed_search"])

    tool_call = make_tool_call("pubmed_search", "{}")
    result = await provider.execute_tool_call(tool_call)

    payload = json.loads(result["content"])
    assert "tool execution failed" in payload["error"]
    assert "server unavailable" in payload["error"]


async def test_execute_known_tool_without_client_errors() -> None:
    """A tracked tool with no client surfaces a ConfigError response."""
    fake = FakeMCPClient(tools={"pubmed_search": object()})
    provider = _make_provider(fake)
    provider.get_tools(mcp_whitelist=["pubmed_search"])
    # Drop the client after names are tracked to force the None branch.
    provider.mcp_client = None

    tool_call = make_tool_call("pubmed_search", "{}")
    result = await provider.execute_tool_call(tool_call)

    payload = json.loads(result["content"])
    assert "tool execution failed" in payload["error"]
    assert "MCP client not configured" in payload["error"]


# --- tracked_executor -------------------------------------------------------


async def test_tracked_executor_counts_calls_per_tool() -> None:
    """The tracked executor counts calls per tool name as it delegates."""
    fake = FakeMCPClient(tools={"pubmed_search": object()})
    provider = _make_provider(fake)
    provider.get_tools(mcp_whitelist=["pubmed_search"])
    executor, counts = provider.tracked_executor("Draft")

    await executor(make_tool_call("pubmed_search", "{}"))
    await executor(make_tool_call("pubmed_search", "{}"))

    assert counts == {"pubmed_search": 2}
    assert len(fake.executed) == 2


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
