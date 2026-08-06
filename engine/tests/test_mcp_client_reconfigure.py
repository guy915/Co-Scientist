"""The shared MCP client must not outlive the configuration it was built for.

``get_mcp_client`` keeps one client per process so the nodes of a run share a
single MCP session instead of each opening its own. The cache was keyed on
nothing at all, though, so the *first* caller's servers were handed to every
later caller: a second run pointed at a different MCP deployment silently
talked to the first one's, and the divergence is invisible from the outside
because the client answers normally -- from the wrong servers.

Reuse still has to be the common case: in a deployment where every run
resolves the same servers, nothing here should build a second transport.
"""

from co_scientist.mcp_client import get_mcp_client
from tests._mcp import FakeMultiServerMCPClient, make_registry, string_tool


async def test_a_different_server_url_builds_a_new_client(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A caller asking for other servers must not get the cached ones."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    first = await get_mcp_client(server_url="http://a.test/mcp")
    second = await get_mcp_client(server_url="http://b.test/mcp")

    assert first is not second
    assert second.server_url == "http://b.test/mcp"


async def test_switching_to_a_registry_builds_a_new_client(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A registry resolving different servers is a configuration change."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    first = await get_mcp_client(server_url="http://a.test/mcp")
    second = await get_mcp_client(tool_registry=make_registry())

    assert first is not second
    assert second.server_url == "http://registry.test/mcp"


async def test_matching_configuration_still_reuses_one_session(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """Sharing one session across a run's nodes is the point of the cache."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    first = await get_mcp_client(tool_registry=make_registry())
    second = await get_mcp_client(tool_registry=make_registry())

    assert first is second
    assert _patch_mcp_seam.instances_created == 1
