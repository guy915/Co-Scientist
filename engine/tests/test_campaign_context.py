from __future__ import annotations

import asyncio
import contextvars
import socket
import sys
from pathlib import Path
from typing import Any

import pytest

from co_scientist.exceptions import FreeModelEligibilityError
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm,
    campaign_free_mode,
    scoped_campaign_mode,
)
from co_scientist.mcp_client import MCPToolClient
from co_scientist.sandbox import ExecResult
from co_scientist.workspace import WorkspaceSession
from co_scientist.workspace.session import SessionRead
from tests._llm_fake import make_completion, make_message, patch_acompletion
from tests._mcp import make_tool_call, string_tool

PAID_MODEL = "openrouter/campaign/paid"
OPTIONS = LLMCallOptions(use_cache=False)


def test_campaign_scope_enables_free_mode_and_cannot_be_relaxed_or_leaked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    delayed = scoped_campaign_mode(False)

    assert not campaign_free_mode()
    with scoped_campaign_mode(True):
        assert campaign_free_mode()
        with scoped_campaign_mode(False):
            assert campaign_free_mode()
        assert campaign_free_mode()
    assert not campaign_free_mode()
    with pytest.raises(RuntimeError, match="boom"), scoped_campaign_mode(True):
        raise RuntimeError("boom")
    assert not campaign_free_mode()
    with scoped_campaign_mode(True), delayed:
        assert campaign_free_mode()


@pytest.mark.parametrize(
    ("flag", "scope", "expected"),
    [("1", False, True), ("sometimes", False, None), ("sometimes", True, None)],
    ids=["global-flag-beats-false-scope", "invalid-flag", "invalid-in-scope"],
)
def test_the_global_flag_stays_authoritative_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
    scope: bool,
    expected: bool | None,
) -> None:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", flag)

    with scoped_campaign_mode(scope):
        if expected is None:
            with pytest.raises(FreeModelEligibilityError, match="setting is invalid"):
                campaign_free_mode()
        else:
            assert campaign_free_mode() is expected


async def test_campaign_scope_is_isolated_between_tasks_and_follows_copies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    ready = asyncio.Event()

    async def observe(enabled: bool) -> bool:
        with scoped_campaign_mode(enabled):
            ready.set()
            await asyncio.sleep(0)
            return campaign_free_mode()

    campaign_task = asyncio.create_task(observe(True))
    await ready.wait()
    ordinary_task = asyncio.create_task(observe(False))
    campaign_result, ordinary_result = await asyncio.gather(campaign_task, ordinary_task)
    assert campaign_result is True
    assert ordinary_result is False
    assert not campaign_free_mode()
    with scoped_campaign_mode(True):
        copied = contextvars.copy_context()
        assert await asyncio.to_thread(copied.run, campaign_free_mode)
    assert not campaign_free_mode()


async def test_campaign_scope_rejects_paid_byok_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.llm.admission import free_policy

    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    monkeypatch.setattr(
        free_policy,
        "current_catalog",
        lambda: {
            "campaign/paid": {
                "pricing": {
                    "prompt": "0.01",
                    "completion": "0.02",
                    "request": "0.03",
                    "internal_reasoning": "0.04",
                    "input_cache_read": "0.05",
                    "input_cache_write": "0.06",
                },
                "architecture": {
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                },
            }
        },
    )
    requests: list[dict[str, object]] = []
    patch_acompletion(
        monkeypatch,
        [make_completion(make_message("ordinary"))],
        requests,
    )
    spec = CompletionSpec(PAID_MODEL, api_key="byok-test-key")

    async def campaign_call() -> None:
        with (
            scoped_campaign_mode(True),
            pytest.raises(
                FreeModelEligibilityError,
                match="zero-cost route has paid or invalid pricing",
            ),
        ):
            await call_llm("probe", spec, options=OPTIONS)

    async def ordinary_call() -> str:
        with scoped_campaign_mode(False):
            return await call_llm("probe", spec, options=OPTIONS)

    campaign_result, ordinary_result = await asyncio.gather(campaign_call(), ordinary_call())
    assert campaign_result is None
    assert ordinary_result == "ordinary"
    assert len(requests) == 1
    assert requests[0]["model"] == PAID_MODEL
    assert requests[0]["api_key"] == "byok-test-key"


URL = "http://localhost:8888/mcp"


@pytest.mark.parametrize("url", ["https://other.example/mcp", URL])
async def test_campaign_rejects_unqualified_server_before_discovery(
    monkeypatch: pytest.MonkeyPatch, _patch_mcp_seam: Any, url: str
) -> None:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.delenv("COSCIENTIST_CAMPAIGN_MCP_URL", raising=False)
    _patch_mcp_seam.tools = [string_tool("search_pubmed", "{}")]
    with pytest.raises(RuntimeError, match="campaign"):
        await MCPToolClient(server_url=url).initialize()


@pytest.mark.parametrize("model_call", [False, True])
async def test_campaign_rejects_preexisting_unqualified_tool_binding(
    monkeypatch: pytest.MonkeyPatch, _patch_mcp_seam: Any, model_call: bool
) -> None:
    _patch_mcp_seam.tools = [string_tool("search_web", "paid result")]
    client = MCPToolClient(server_url=URL)
    await client.initialize()
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    with pytest.raises(RuntimeError, match="campaign"):
        if model_call:
            await client.execute_tool_call(make_tool_call("search_web", "{}"))
        else:
            await client.call_tool("search_web")


@pytest.fixture
def qualified(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import httpx
    from mcp_server.campaign import campaign_policy

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_CAMPAIGN_MCP_URL", URL)
    monkeypatch.setenv("COSCIENTIST_MCP_SHARED_SECRET", "secret")
    data = {
        "service": "coscientist-lit-review",
        "campaign_policy": campaign_policy(),
    }
    original = httpx.AsyncClient

    def reply(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://localhost:8888/"
        assert request.headers["X-CoScientist-Campaign"] == "1"
        assert request.headers["X-MCP-Shared-Secret"] == "secret"
        return httpx.Response(200, json=data)

    def client(**kwargs: Any) -> httpx.AsyncClient:
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return original(**kwargs, transport=httpx.MockTransport(reply))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return data


@pytest.mark.parametrize("model_call", [False, True])
async def test_qualified_calls_recheck_policy_and_hide_unqualified_tools(
    qualified: dict[str, Any], _patch_mcp_seam: Any, model_call: bool
) -> None:
    _patch_mcp_seam.tools = [
        string_tool("search_pubmed", "public evidence"),
        string_tool("search_web", "paid"),
    ]
    client = MCPToolClient(server_url=URL)
    await client.initialize()
    tools, schemas = client.get_tools()
    assert set(tools) == {"search_pubmed"}
    assert [s["function"]["name"] for s in schemas] == ["search_pubmed"]

    async def invoke(name: str) -> Any:
        if model_call:
            return await client.execute_tool_call(make_tool_call(name, "{}"))
        return await client.call_tool(name)

    assert "public evidence" in str(await invoke("search_pubmed"))
    with pytest.raises(RuntimeError, match="campaign"):
        await invoke("search_web")
    qualified["campaign_policy"]["enabled"] = False
    with pytest.raises(RuntimeError, match="campaign"):
        await invoke("search_pubmed")


@pytest.mark.parametrize(
    ("deployment", "expected_additions"),
    [
        ("m10", {"get_opencitations_citation_edges"}),
        (
            "m11",
            {
                "get_opencitations_citation_edges",
                "search_gwas_catalog_associations",
            },
        ),
        ("pre_citation_rollback", set()),
    ],
)
async def test_client_accepts_real_deployment_manifests_during_rollout(
    qualified: dict[str, Any],
    _patch_mcp_seam: Any,
    deployment: str,
    expected_additions: set[str],
) -> None:
    current_tools = set(qualified["campaign_policy"]["tools"])
    assert {
        "get_opencitations_citation_edges",
        "search_gwas_catalog_associations",
    } <= current_tools
    manifest_tools = {
        "m10": current_tools - {"search_gwas_catalog_associations"},
        "m11": current_tools,
        "pre_citation_rollback": current_tools
        - {
            "get_opencitations_citation_edges",
            "search_gwas_catalog_associations",
        },
    }[deployment]
    qualified["campaign_policy"]["tools"] = sorted(manifest_tools)

    tool_text = {
        "search_pubmed": "public evidence",
        "get_opencitations_citation_edges": "citation edges",
        "search_gwas_catalog_associations": "GWAS associations",
    }
    _patch_mcp_seam.tools = [string_tool("search_pubmed", "public evidence")]
    _patch_mcp_seam.tools.extend(string_tool(name, tool_text[name]) for name in expected_additions)

    client = MCPToolClient(server_url=URL)
    await client.initialize()
    tool_map, _ = client.get_tools()
    assert set(tool_map) == {"search_pubmed", *expected_additions}
    for name in expected_additions:
        assert tool_text[name] in str(await client.call_tool(name))

    if deployment == "m10":
        # An older bound client must tolerate an advancing server manifest.
        qualified["campaign_policy"]["tools"] = sorted(current_tools)
        assert "public evidence" in str(await client.call_tool("search_pubmed"))

    qualified["campaign_policy"]["tools"].append("unqualified_paid_tool")
    with pytest.raises(RuntimeError, match="campaign"):
        await client.call_tool("search_pubmed")


async def test_client_rejects_gwas_manifest_without_m10_citation_tool(
    qualified: dict[str, Any], _patch_mcp_seam: Any
) -> None:
    tools = set(qualified["campaign_policy"]["tools"])
    tools.remove("get_opencitations_citation_edges")
    qualified["campaign_policy"]["tools"] = sorted(tools)
    with pytest.raises(RuntimeError, match="campaign"):
        await MCPToolClient(server_url=URL).initialize()
    assert _patch_mcp_seam.instances_created == 0


@pytest.mark.parametrize("change", ["url", "transport", "headers", "extra", "multi"])
async def test_custom_configuration_is_rejected_before_sdk_connection(
    qualified: dict[str, Any], _patch_mcp_seam: Any, change: str
) -> None:
    config: dict[str, Any] = {"transport": "streamable_http", "url": URL}
    changes: dict[str, dict[str, Any]] = {
        "url": {"url": "https://unqualified.example/mcp"},
        "transport": {"transport": "stdio"},
        "headers": {"headers": {"Authorization": "fake"}},
        "extra": {"httpx_client_factory": lambda: None},
        "multi": {},
    }
    config.update(changes[change])
    configs = {"one": config}
    if change == "multi":
        configs["two"] = dict(config)
    with pytest.raises(RuntimeError, match="campaign"):
        await MCPToolClient(server_configs=configs).initialize()
    assert _patch_mcp_seam.instances_created == 0


@pytest.mark.parametrize("mutation", [None, {"version": "old"}, {"enabled": False}])
async def test_unqualified_serving_policy_prevents_tool_discovery(
    qualified: dict[str, Any], _patch_mcp_seam: Any, mutation: Any
) -> None:
    qualified["campaign_policy"] = mutation
    with pytest.raises(RuntimeError, match="campaign"):
        await MCPToolClient(server_url=URL).initialize()
    assert _patch_mcp_seam.instances_created == 0


async def test_mutated_binding_cannot_redirect_existing_tools(
    qualified: dict[str, Any], _patch_mcp_seam: Any
) -> None:
    _patch_mcp_seam.tools = [string_tool("search_pubmed", "public")]
    client = MCPToolClient(server_url=URL)
    await client.initialize()
    client._server_configs["default"]["url"] = "https://unqualified.example/mcp"
    with pytest.raises(RuntimeError, match="campaign"):
        await client.call_tool("search_pubmed")


async def test_global_client_created_outside_campaign_cannot_be_reused(
    monkeypatch: pytest.MonkeyPatch, _patch_mcp_seam: Any
) -> None:
    from co_scientist.mcp_client import get_mcp_client

    _patch_mcp_seam.tools = [string_tool("search_pubmed", "unqualified")]
    await get_mcp_client(server_url=URL)
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    with pytest.raises(RuntimeError, match="campaign"):
        await get_mcp_client()


async def test_qualified_sdk_transport_has_no_redirect_or_proxy_escape(
    qualified: dict[str, Any], _patch_mcp_seam: Any
) -> None:
    from co_scientist.mcp_client import campaign_http_client

    client = MCPToolClient(server_url=URL)
    await client.initialize()
    assert client._client is not None
    connection = client._client.connections["default"]
    assert connection["transport"] == "streamable_http"
    factory = connection["httpx_client_factory"]
    assert factory is campaign_http_client
    async with factory() as transport:
        assert transport.follow_redirects is False
        assert transport.trust_env is False


@pytest.mark.parametrize("surface", ["schemas", "availability"])
async def test_unqualified_cached_tools_are_not_advertised_in_campaign(
    monkeypatch: pytest.MonkeyPatch, _patch_mcp_seam: Any, surface: str
) -> None:
    _patch_mcp_seam.tools = [string_tool("search_web", "paid")]
    client = MCPToolClient(server_url=URL)
    await client.initialize()
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    with pytest.raises(RuntimeError, match="campaign"):
        if surface == "schemas":
            client.get_tools()
        else:
            client.has_tool("search_web")


@pytest.mark.parametrize("persistent", [False, True])
async def test_campaign_confines_preexisting_network_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, persistent: bool
) -> None:
    session = WorkspaceSession(tmp_path, network_allowed=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        program = (
            "import socket\n"
            "print('LOCAL_OK', sum(range(10)), flush=True)\n"
            "try:\n"
            f"    socket.create_connection(('127.0.0.1', {port}),\n"
            "                             timeout=2).close()\n"
            "except OSError:\n"
            "    print('NETWORK_DENIED')\n"
            "else:\n"
            "    print('NETWORK_REACHED')\n"
        )
        argv = [sys.executable, "-c", program]
        control = await session.run_command(argv)
        assert control.result.ok, control.result.stderr
        assert "NETWORK_REACHED" in control.result.stdout
        monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
        result: ExecResult | SessionRead
        if persistent:
            command = await session.sessions.start(argv, policy=session.policy, cwd=session.root)
            await command.wait_for(10)
            result = command.read()
        else:
            result = (await session.run_command(argv)).result
        assert result.exit_code == 0, result.stderr
        assert "LOCAL_OK 45" in result.stdout
        assert "NETWORK_DENIED" in result.stdout
        assert "NETWORK_REACHED" not in result.stdout


def test_campaign_does_not_inject_skill_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.skills import skill_environment

    monkeypatch.setenv("OPENALEX_API_KEY", "test-only-key")
    assert skill_environment()["OPENALEX_API_KEY"] == "test-only-key"
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    assert skill_environment() == {}


@pytest.mark.parametrize("kind", ["external", "danger_full_access"])
def test_campaign_rejects_unverified_confinement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    from co_scientist.sandbox import SandboxKind, SandboxPolicy

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    with pytest.raises(RuntimeError, match="campaign"):
        WorkspaceSession(tmp_path, policy=SandboxPolicy(kind=SandboxKind(kind)))


def test_campaign_schema_for_preexisting_workspace_is_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from co_scientist.workspace.tools import WorkspaceToolProvider

    session = WorkspaceSession(tmp_path, network_allowed=True)
    provider = WorkspaceToolProvider(session)
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    _, schemas = provider.get_tools()
    command = next(s["function"] for s in schemas if s["function"]["name"] == "run_command")
    assert "not reach the network" in command["description"].lower()


async def test_recognized_skill_receives_no_campaign_host_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import json

    import co_scientist.skills as catalog
    import co_scientist.skills as usage
    from co_scientist.workspace import WorkspaceToolProvider
    from tests._mcp import make_tool_call

    skills = tmp_path / "skills"
    skill = skills / "public-example"
    script = skill / "scripts" / "cli.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "import os\n"
        "print('CREDENTIAL_PRESENT' if os.getenv('OPENALEX_API_KEY') "
        "else 'CREDENTIAL_ABSENT')\n"
    )
    (skill / "SKILL.md").write_text(
        "---\nname: public-example\ndescription: Example query.\n---\nBody.\n"
    )
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(skills))
    monkeypatch.setenv(catalog.SKILLS_PYTHON_ENV, sys.executable)
    monkeypatch.setenv("OPENALEX_API_KEY", "synthetic-only")
    catalog.available_skills.cache_clear()
    try:
        session = WorkspaceSession(tmp_path / "work", skills_enabled=True)
        provider = WorkspaceToolProvider(session)
        call = make_tool_call(
            "run_command",
            json.dumps({"argv": [sys.executable, str(script)]}),
        )
        control = json.loads((await provider.execute_tool_call(call))["content"])
        assert "CREDENTIAL_PRESENT" in control["stdout"]
        monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
        with usage.scoped_skill_usage() as tally:
            result = json.loads((await provider.execute_tool_call(call))["content"])
        assert tally.snapshot() == {}
        assert result["exit_code"] == 0, result
        assert "CREDENTIAL_ABSENT" in result["stdout"]
        stale_read = await provider.execute_tool_call(
            make_tool_call("read_skill", json.dumps({"name": "public-example"}))
        )
        assert "unavailable in campaign" in stale_read["content"]
    finally:
        catalog.available_skills.cache_clear()
