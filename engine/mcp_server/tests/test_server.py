import asyncio
import inspect
import logging
from typing import Any

import httpx
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from mcp_server.auth_middleware import (
    MCP_AUTH_HEADER,
    MCP_CAMPAIGN_HEADER,
    MCP_SHARED_SECRET_ENV,
    SharedSecretAuthMiddleware,
    resolve_shared_secret,
)
from mcp_server.campaign import campaign_free_mode
from mcp_server.tests._httpx import asgi_client_factory
from mcp_server.tool_logging import with_call_logging
from mcp_server.tools import web_providers as providers
from mcp_server.tools.lit_review.openalex_search import search_openalex
from mcp_server.tools.web_providers import (
    check_web_search_available,
    search_web,
)
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


async def _root(request):  # type: ignore[no-untyped-def]
    return PlainTextResponse(f"status:{campaign_free_mode()}")


async def _tool_endpoint(request):  # type: ignore[no-untyped-def]
    return PlainTextResponse(f"tool result:{campaign_free_mode()}")


def _make_app(secret: str | None) -> Starlette:
    app = Starlette(
        routes=[
            Route("/", _root),
            Route("/mcp", _tool_endpoint, methods=["POST"]),
        ]
    )
    app.add_middleware(SharedSecretAuthMiddleware, secret=secret)
    return app


def test_unset_secret_allows_every_request() -> None:
    client = TestClient(_make_app(secret=None))

    response = client.post("/mcp")

    assert response.status_code == 200
    assert response.text == "tool result:False"


def test_configured_secret_rejects_missing_header() -> None:
    client = TestClient(_make_app(secret="s3cret"))

    response = client.post("/mcp")

    assert response.status_code == 401


def test_configured_secret_rejects_wrong_header() -> None:
    client = TestClient(_make_app(secret="s3cret"))

    response = client.post("/mcp", headers={MCP_AUTH_HEADER: "wrong"})

    assert response.status_code == 401


@pytest.mark.parametrize("host", ["example.com/#", "example.com/?"])
def test_host_path_cannot_exempt_an_unauthenticated_tool_call(
    host: str,
) -> None:
    client = TestClient(_make_app(secret="s3cret"))
    response = client.post("/mcp", headers={"Host": host})
    assert response.status_code in {400, 401}


def test_configured_secret_accepts_matching_header() -> None:
    client = TestClient(_make_app(secret="s3cret"))

    response = client.post("/mcp", headers={MCP_AUTH_HEADER: "s3cret"})

    assert response.status_code == 200
    assert response.text == "tool result:False"


def test_status_route_stays_exempt_even_with_secret_set() -> None:
    client = TestClient(_make_app(secret="s3cret"))

    response = client.get("/")

    assert response.status_code == 200


def test_campaign_header_requires_matching_shared_secret_on_root() -> None:
    client = TestClient(_make_app(secret="s3cret"))

    missing = client.get("/", headers={MCP_CAMPAIGN_HEADER: "1"})
    forged = client.get(
        "/",
        headers={MCP_CAMPAIGN_HEADER: "1", MCP_AUTH_HEADER: "wrong"},
    )

    assert missing.status_code == 401
    assert forged.status_code == 401


def test_authenticated_campaign_root_reports_campaign_policy() -> None:
    client = TestClient(_make_app(secret="s3cret"))

    response = client.get(
        "/",
        headers={
            MCP_CAMPAIGN_HEADER: "1",
            MCP_AUTH_HEADER: "s3cret",
        },
    )

    assert response.status_code == 200
    assert response.text == "status:True"


def test_campaign_header_fails_closed_without_server_secret() -> None:
    client = TestClient(_make_app(secret=None))

    response = client.post("/mcp", headers={MCP_CAMPAIGN_HEADER: "1"})

    assert response.status_code == 401


def test_authenticated_campaign_request_is_scoped_and_resets() -> None:
    client = TestClient(_make_app(secret="s3cret"))
    headers = {MCP_CAMPAIGN_HEADER: "1", MCP_AUTH_HEADER: "s3cret"}

    campaign = client.post("/mcp", headers=headers)
    ordinary = client.post("/mcp", headers={MCP_AUTH_HEADER: "s3cret"})

    assert campaign.text == "tool result:True"
    assert ordinary.text == "tool result:False"


def test_resolve_shared_secret_reads_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(MCP_SHARED_SECRET_ENV, raising=False)
    assert resolve_shared_secret() is None

    monkeypatch.setenv(MCP_SHARED_SECRET_ENV, "token-123")
    assert resolve_shared_secret() == "token-123"

    monkeypatch.setenv(MCP_SHARED_SECRET_ENV, "")
    assert resolve_shared_secret() is None


async def test_concurrent_fastmcp_sessions_receive_request_policy() -> None:
    both_entered = asyncio.Event()
    entered = 0
    lock = asyncio.Lock()

    async def inspect_policy(label: str) -> dict[str, object]:
        nonlocal entered
        async with lock:
            entered += 1
            if entered == 2:
                both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=2)
        return {"label": label, "campaign": campaign_free_mode()}

    mcp = FastMCP("campaign-context-test")
    mcp.tool(
        with_call_logging(inspect_policy, "search_pubmed"),
        name="search_pubmed",
    )
    mcp_app = mcp.http_app()
    app = Starlette(lifespan=mcp_app.lifespan)
    app.mount("/", mcp_app)
    app.add_middleware(SharedSecretAuthMiddleware, secret="secret")
    factory = asgi_client_factory(app)

    async def invoke(label: str, campaign: bool) -> Any:
        headers = {MCP_AUTH_HEADER: "secret"}
        if campaign:
            headers[MCP_CAMPAIGN_HEADER] = "1"
        transport = StreamableHttpTransport(
            "http://test/mcp",
            headers=headers,
            httpx_client_factory=factory,
        )
        async with Client(transport) as client:
            return await client.call_tool("search_pubmed", {"label": label})

    async with app.router.lifespan_context(app):
        campaign, ordinary = await asyncio.gather(
            invoke("campaign", True), invoke("ordinary", False)
        )
        ordinary_after = await invoke("ordinary-after", False)

    assert campaign.data == {"label": "campaign", "campaign": True}
    assert ordinary.data == {"label": "ordinary", "campaign": False}
    assert ordinary_after.data == {
        "label": "ordinary-after",
        "campaign": False,
    }
    assert campaign_free_mode() is False


@pytest.fixture
def campaign(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    for name in ("BRAVE_API_KEY", "TAVILY_API_KEY", "OPENALEX_API_KEY"):
        monkeypatch.setenv(name, "test-paid-account")


@pytest.mark.parametrize("provider", ["brave", "tavily"])
async def test_campaign_blocks_direct_metered_search(
    campaign: None, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    sent = []

    def client(**kwargs: Any) -> Any:
        sent.append(kwargs)
        raise AssertionError("metered transport opened")

    monkeypatch.setattr(httpx, "AsyncClient", client)
    with pytest.raises(RuntimeError, match="campaign"):
        await getattr(providers, f"search_{provider}")("research", 2, 0)
    assert sent == []


async def test_campaign_exposes_no_paid_search_or_fallback(
    campaign: None,
) -> None:
    assert providers.configured_providers() == []
    assert providers.candidate_providers() == []
    assert providers.resolve_provider() is None
    assert not await check_web_search_available()
    assert await search_web("public research") == {}


async def test_campaign_openalex_does_not_attach_host_account(
    campaign: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[httpx.Request] = []
    original = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"results": []})

    def client(**kwargs: Any) -> httpx.AsyncClient:
        assert kwargs["trust_env"] is False
        return original(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    assert await search_openalex("public research") == {}
    assert len(sent) == 1
    assert "api_key" not in sent[0].url.params
    assert "authorization" not in sent[0].headers


@pytest.mark.parametrize("setting", ["1", "true", " TRUE ", "invalid"])
@pytest.mark.parametrize("provider", ["brave", "tavily"])
async def test_enabled_or_invalid_mode_never_opens_web_transport(
    monkeypatch: pytest.MonkeyPatch, setting: str, provider: str
) -> None:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", setting)

    def refuse(**kwargs: Any) -> Any:
        raise AssertionError("transport opened")

    monkeypatch.setattr(httpx, "AsyncClient", refuse)
    with pytest.raises(RuntimeError, match="campaign"):
        await getattr(providers, f"search_{provider}")("public", 1, 0)


@pytest.mark.parametrize("setting", ["0", "false", ""])
async def test_normal_openalex_preserves_explicit_host_key(
    monkeypatch: pytest.MonkeyPatch, setting: str
) -> None:
    from mcp_server.tests._httpx import stub_responses

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", setting)
    monkeypatch.setenv("OPENALEX_API_KEY", "test-user-key")
    client = stub_responses(monkeypatch, {"results": []})
    await search_openalex("public")
    assert client.calls[0][1]["api_key"] == "test-user-key"


async def test_openalex_quota_refusal_does_not_retry_with_host_key(
    campaign: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcp_server.tests._httpx import stub_failure
    from mcp_server.tools.lit_review.openalex_search import (
        OpenAlexUnavailableError,
    )

    response = httpx.Response(
        429, request=httpx.Request("GET", "https://api.openalex.org/works")
    )
    client = stub_failure(
        monkeypatch,
        httpx.HTTPStatusError(
            "quota", request=response.request, response=response
        ),
    )
    with pytest.raises(OpenAlexUnavailableError):
        await search_openalex("public")
    assert len(client.calls) == 1
    assert "api_key" not in client.calls[0][1]


def test_campaign_server_boot_omits_metered_web_tools() -> None:
    import os
    import subprocess
    import sys

    script = """
from mcp_server.server import _MCP_TOOLS
names = {name for _, name in _MCP_TOOLS}
assert 'search_web' not in names
assert 'check_web_search_available' not in names
assert 'search_pubmed' in names
from mcp_server.campaign import PUBLIC_TOOLS, campaign_policy
assert names == PUBLIC_TOOLS
assert campaign_policy()['enabled'] is True
from mcp_server.server import root
import asyncio, json
body = json.loads(asyncio.run(root()).body)
assert body['campaign_policy'] == campaign_policy()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={
            "PATH": os.defpath,
            "PYTHON_DOTENV_DISABLED": "1",
            "COSCIENTIST_REQUIRE_FREE_MODELS": "1",
            "BRAVE_API_KEY": "fake",
            "TAVILY_API_KEY": "fake",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


async def test_invalid_mode_blocks_openalex_and_provider_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "yes")

    def refuse(**kwargs: Any) -> Any:
        raise AssertionError("transport opened")

    monkeypatch.setattr(httpx, "AsyncClient", refuse)
    with pytest.raises(RuntimeError, match="invalid"):
        await search_openalex("public")
    with pytest.raises(RuntimeError, match="invalid"):
        await check_web_search_available()
    with pytest.raises(RuntimeError, match="invalid"):
        await search_web("public")


@pytest.mark.parametrize(
    "name", ["search_web", "query_drug_info", "read_url", "new_tool"]
)
async def test_campaign_rejects_unqualified_registered_calls(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    reached = []

    async def tool() -> dict[str, Any]:
        reached.append(name)
        return {}

    wrapped = with_call_logging(tool, name)
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    with pytest.raises(RuntimeError, match="campaign"):
        await wrapped()
    assert reached == []


def test_campaign_rejects_sync_registered_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def tool() -> str:
        raise AssertionError("unqualified sync tool ran")

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    with pytest.raises(RuntimeError, match="campaign"):
        with_call_logging(tool, "unqualified")()


async def test_campaign_retains_public_tool_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def tool() -> str:
        return "public evidence"

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    assert await with_call_logging(tool, "search_pubmed")() == "public evidence"


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
    """Provider failure, missing keys and no matches all return empty
    results; logs distinguish calls."""

    def nothing(q: str) -> str:
        return "{}"

    with caplog.at_level(logging.INFO):
        with_call_logging(nothing, "nothing")("zzz")
    assert "-> empty" in caplog.text


def test_logs_dict_returning_tools(caplog: pytest.LogCaptureFixture) -> None:

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
    assert "upstream down" in caplog.text


def test_wraps_async_tools(caplog: pytest.LogCaptureFixture) -> None:

    async def fetch(q: str) -> str:
        return '{"a": 1}'

    wrapped = with_call_logging(fetch, "fetch")
    assert inspect.iscoroutinefunction(wrapped)
    with caplog.at_level(logging.INFO):
        assert asyncio.run(wrapped("q")) == '{"a": 1}'
    assert "tool fetch(" in caplog.text


def test_preserves_the_signature_fastmcp_advertises() -> None:
    """FastMCP derives advertised parameters from the signature; a generic
    wrapper erases them."""

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
    assert len(max(caplog.text.split("\n"), key=len)) < 400


def test_returns_the_result_unchanged() -> None:

    def tool(q: str) -> str:
        return '{"untouched": true}'

    assert with_call_logging(tool, "tool")("q") == '{"untouched": true}'
