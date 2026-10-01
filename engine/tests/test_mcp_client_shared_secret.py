"""Tests for the MCP client's shared-secret header (N7).

The reference MCP server (``engine/mcp_server/auth_middleware.py``) accepts a
shared-secret header and rejects requests lacking it once
``COSCIENTIST_MCP_SHARED_SECRET`` is configured. This is the client half:
every path that resolves server configs -- explicit configs, the legacy
single-URL fallback, and (indirectly) the tool-registry path -- must attach
the same header, and must do nothing when the variable is unset.
"""

import pytest

from co_scientist.mcp_client import MCPToolClient
from co_scientist.mcp_client.helpers import (
    MCP_AUTH_HEADER,
    MCP_SHARED_SECRET_ENV,
    _resolve_server_configs,
)


def test_unset_secret_sends_no_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the env var unset, resolved configs carry no headers at all.

    This is the "unset variable keeps the current behaviour" requirement:
    a deployment that has not adopted the secret must send exactly the
    request shape it always has.
    """
    monkeypatch.delenv(MCP_SHARED_SECRET_ENV, raising=False)

    configs = _resolve_server_configs(None, None, "http://x.test/mcp")

    assert "headers" not in configs["default"]


def test_configured_secret_is_attached_to_legacy_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(MCP_SHARED_SECRET_ENV, "topsecret")

    configs = _resolve_server_configs(None, None, "http://x.test/mcp")

    assert configs["default"]["headers"] == {MCP_AUTH_HEADER: "topsecret"}


def test_configured_secret_is_attached_to_explicit_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(MCP_SHARED_SECRET_ENV, "topsecret")
    explicit = {
        "s1": {"transport": "streamable_http", "url": "http://s1.test/mcp"},
    }

    configs = _resolve_server_configs(None, explicit, None)

    assert configs["s1"]["headers"] == {MCP_AUTH_HEADER: "topsecret"}
    # The input dict is not mutated in place.
    assert "headers" not in explicit["s1"]


def test_configured_secret_merges_with_existing_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-supplied header on the config survives alongside the secret."""
    monkeypatch.setenv(MCP_SHARED_SECRET_ENV, "topsecret")
    explicit = {
        "s1": {
            "transport": "streamable_http",
            "url": "http://s1.test/mcp",
            "headers": {"X-Other": "kept"},
        },
    }

    configs = _resolve_server_configs(None, explicit, None)

    assert configs["s1"]["headers"] == {
        "X-Other": "kept",
        MCP_AUTH_HEADER: "topsecret",
    }


def test_empty_secret_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(MCP_SHARED_SECRET_ENV, "")

    configs = _resolve_server_configs(None, None, "http://x.test/mcp")

    assert "headers" not in configs["default"]


def test_mcp_tool_client_carries_the_header_through_server_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The header reaches MCPToolClient's own resolved server config."""
    monkeypatch.setenv(MCP_SHARED_SECRET_ENV, "topsecret")

    client = MCPToolClient(server_url="http://x.test/mcp")

    assert client._server_configs["default"]["headers"] == {
        MCP_AUTH_HEADER: "topsecret"
    }
