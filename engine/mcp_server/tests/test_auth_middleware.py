"""Tests for the MCP server's shared-secret auth middleware.

The server has no auth of its own beyond network placement (see N7 in
docs/fidelity-audit/FINDINGS.md); this middleware is the inner control.
Built against a minimal Starlette app rather than importing
``mcp_server.server`` directly, since that module registers every real tool
and reads live process environment at import time.
"""

import pytest
from mcp_server.auth_middleware import (
    MCP_AUTH_HEADER,
    MCP_CAMPAIGN_HEADER,
    MCP_SHARED_SECRET_ENV,
    SharedSecretAuthMiddleware,
    resolve_shared_secret,
)
from mcp_server.campaign import campaign_free_mode
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
    """No env var set reproduces today's behaviour: nothing is checked."""
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


def test_configured_secret_accepts_matching_header() -> None:
    client = TestClient(_make_app(secret="s3cret"))

    response = client.post("/mcp", headers={MCP_AUTH_HEADER: "s3cret"})

    assert response.status_code == 200
    assert response.text == "tool result:False"


def test_status_route_stays_exempt_even_with_secret_set() -> None:
    """The plain status route is what Compose's own healthcheck probes."""
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
