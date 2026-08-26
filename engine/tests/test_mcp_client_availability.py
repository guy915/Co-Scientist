"""Tests for MCP availability checks, global caching and the registry path.

Covers ``check_mcp_available``, ``check_literature_source_available``, the
``get_mcp_client`` global cache, and the config-driven multi-server
(``ToolRegistry``) path.
Construction and the ``MCPToolClient`` instance API are covered in
``test_mcp_client_core``.

The external ``MultiServerMCPClient`` transport is replaced by the
``_patch_mcp_seam`` fixture (in ``conftest``) with an in-memory fake, so no
server is ever contacted; ``FakeToolRegistry`` stands in for the real registry
to exercise the multi-server availability and tool-to-server mapping logic.
"""

from co_scientist.mcp_client import (
    MCPToolClient,
    check_literature_source_available,
    check_mcp_available,
    check_web_search_available,
    get_mcp_client,
    reset_mcp_client,
)
from tests._mcp import FakeMultiServerMCPClient, make_registry, string_tool

# --- check_mcp_available: three outcomes ------------------------------------


async def test_check_mcp_available_true_when_tools_present(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A server that returns at least one tool is reported available."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    assert await check_mcp_available(server_url="http://x.test/mcp") is True


async def test_check_mcp_available_false_when_no_tools(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A server responding with an empty tool list is reported unavailable."""
    _patch_mcp_seam.tools = []
    assert await check_mcp_available(server_url="http://x.test/mcp") is False


async def test_check_mcp_available_false_on_connection_error(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A transport error degrades gracefully to False, no exception escapes."""
    _patch_mcp_seam.error = ConnectionError("boom")
    assert await check_mcp_available(server_url="http://x.test/mcp") is False


# --- check_literature_source_available --------------------------------------


async def test_literature_source_true_when_check_tool_returns_true_string(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """The default check tool returning the string "true" yields True."""
    _patch_mcp_seam.tools = [
        string_tool("check_pubmed_available", "true"),
        string_tool("pubmed_search", "{}"),
    ]
    assert (
        await check_literature_source_available(server_url="http://x.test/mcp")
        is True
    )


async def test_literature_source_true_when_check_tool_returns_bool(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A check tool returning a real bool True yields True."""
    _patch_mcp_seam.tools = [
        string_tool("check_pubmed_available", True),
    ]
    assert (
        await check_literature_source_available(server_url="http://x.test/mcp")
        is True
    )


async def test_literature_source_false_when_check_tool_returns_false_string(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A check tool returning "false" yields False."""
    _patch_mcp_seam.tools = [
        string_tool("check_pubmed_available", "false"),
    ]
    assert (
        await check_literature_source_available(server_url="http://x.test/mcp")
        is False
    )


async def test_literature_source_false_when_check_tool_absent(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """If the default check tool is missing from the server, returns False."""
    _patch_mcp_seam.tools = [string_tool("some_other_tool", "{}")]
    assert (
        await check_literature_source_available(server_url="http://x.test/mcp")
        is False
    )


async def test_literature_source_false_when_server_has_no_tools(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """If the MCP server reports no tools, the source is unavailable."""
    _patch_mcp_seam.tools = []
    assert (
        await check_literature_source_available(server_url="http://x.test/mcp")
        is False
    )


async def test_literature_source_false_on_connection_error(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A transport error degrades gracefully to False."""
    _patch_mcp_seam.error = RuntimeError("down")
    assert (
        await check_literature_source_available(server_url="http://x.test/mcp")
        is False
    )


# --- get_mcp_client / global caching ----------------------------------------


async def test_get_mcp_client_caches_single_instance(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """Repeated get_mcp_client calls return the same cached client."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    first = await get_mcp_client(server_url="http://x.test/mcp")
    second = await get_mcp_client(server_url="http://x.test/mcp")

    assert first is second
    # The transport is constructed once: the second call reuses the cached
    # client and initialize() short-circuits.
    assert _patch_mcp_seam.instances_created == 1
    assert first.has_tool("t1")


async def test_get_mcp_client_force_new_rebuilds(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """force_new builds a fresh client and a fresh transport connection."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    first = await get_mcp_client(server_url="http://x.test/mcp")
    second = await get_mcp_client(
        server_url="http://x.test/mcp", force_new=True
    )

    assert first is not second
    assert _patch_mcp_seam.instances_created == 2


async def test_reset_mcp_client_clears_global(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """After reset, the next get_mcp_client builds a brand-new client."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    first = await get_mcp_client(server_url="http://x.test/mcp")
    reset_mcp_client()
    second = await get_mcp_client(server_url="http://x.test/mcp")

    assert first is not second
    assert _patch_mcp_seam.instances_created == 2


# --- Registry / config-driven multi-server path -----------------------------


def test_init_with_registry_uses_registry_server_configs() -> None:
    """A tool_registry drives the server configs and surfaced server_url."""
    client = MCPToolClient(tool_registry=make_registry())
    assert client.server_url == "http://registry.test/mcp"


async def test_initialize_with_registry_tracks_tool_to_server(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """Registry-driven initialize records the server that provides each tool."""
    _patch_mcp_seam.tools = [
        string_tool("pubmed_search", "{}"),
        string_tool("orphan_tool", "{}"),
    ]
    registry = make_registry(
        mcp_name_to_server={"pubmed_search": "pubmed_server"}
    )
    client = MCPToolClient(tool_registry=registry)
    await client.initialize()

    # initialize records the providing server for each tool in the map that
    # backed the (now-removed) get_server_for_tool accessor.
    assert client._tool_to_server.get("pubmed_search") == "pubmed_server"
    # A tool the registry doesn't know about maps to no server.
    assert client._tool_to_server.get("orphan_tool") is None


async def test_check_mcp_available_with_registry_true(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """check_mcp_available works through the registry multi-server path."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    assert await check_mcp_available(tool_registry=make_registry()) is True


async def test_literature_source_registry_explicit_check_tool_true(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """An explicit availability_check tool that returns "true" yields True."""
    _patch_mcp_seam.tools = [
        string_tool("check_pubmed_available", "true"),
        string_tool("pubmed_search", "{}"),
    ]
    registry = make_registry(
        availability_check="check_avail",
        check_mcp_tool_name="check_pubmed_available",
    )
    assert (
        await check_literature_source_available(tool_registry=registry) is True
    )


async def test_literature_source_registry_check_tool_missing_returns_false(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A configured check tool absent from the live server yields False."""
    _patch_mcp_seam.tools = [string_tool("pubmed_search", "{}")]
    registry = make_registry(
        availability_check="check_avail",
        check_mcp_tool_name="check_pubmed_available",
    )
    assert (
        await check_literature_source_available(tool_registry=registry) is False
    )


async def test_literature_source_registry_null_check_assumes_available(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """``availability_check: null`` returns True without calling any check tool.

    The only requirement is that the MCP server is up (returns tools); no
    source-specific availability tool is invoked.
    """
    _patch_mcp_seam.tools = [string_tool("pubmed_search", "{}")]
    registry = make_registry(availability_check=None)
    assert (
        await check_literature_source_available(tool_registry=registry) is True
    )


async def test_literature_source_registry_false_when_mcp_down(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """With a registry but no live MCP server, the source is unavailable."""
    _patch_mcp_seam.error = ConnectionError("down")
    registry = make_registry(availability_check=None)
    assert (
        await check_literature_source_available(tool_registry=registry) is False
    )


# --- check_web_search_available ---------------------------------------------
#
# The connector's health used to be read off the presence of ``search_web``,
# which only says a key was set when the server booted. A key the provider
# has since refused leaves the tool listed and every search empty, so the
# status card read "up" while the runs saw nothing.


async def test_web_search_false_when_the_server_reports_a_dead_key(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A listed search_web does not override the server's own verdict."""
    _patch_mcp_seam.tools = [
        string_tool("check_web_search_available", "false"),
        string_tool("search_web", "{}"),
    ]
    assert (
        await check_web_search_available(server_url="http://x.test/mcp")
        is False
    )


async def test_web_search_true_when_the_server_reports_a_usable_key(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """The check tool's affirmative answer is the whole answer."""
    _patch_mcp_seam.tools = [
        string_tool("check_web_search_available", "true"),
        string_tool("search_web", "{}"),
    ]
    assert (
        await check_web_search_available(server_url="http://x.test/mcp") is True
    )


async def test_web_search_falls_back_to_tool_presence_on_older_servers(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """App and MCP server deploy separately; an old image must still pass."""
    _patch_mcp_seam.tools = [string_tool("search_web", "{}")]
    assert (
        await check_web_search_available(server_url="http://x.test/mcp") is True
    )


async def test_web_search_false_when_the_tool_is_absent_entirely(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """No key at boot means no search_web, which is still "not usable"."""
    _patch_mcp_seam.tools = [string_tool("search_pubmed", "{}")]
    assert (
        await check_web_search_available(server_url="http://x.test/mcp")
        is False
    )


async def test_web_search_false_on_connection_error(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """An unreachable server degrades to unavailable, like the other probes."""
    _patch_mcp_seam.error = ConnectionError("boom")
    assert (
        await check_web_search_available(server_url="http://x.test/mcp")
        is False
    )
