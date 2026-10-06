import pytest
from mcp_server.auth_middleware import MCP_AUTH_HEADER, SharedSecretAuthMiddleware
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


async def _root(request):  # type: ignore[no-untyped-def]
    return PlainTextResponse("status")


async def _tool_endpoint(request):  # type: ignore[no-untyped-def]
    return PlainTextResponse("tool result")


def _make_app(secret: str | None) -> Starlette:
    app = Starlette(
        routes=[
            Route("/", _root),
            Route("/mcp", _tool_endpoint, methods=["POST"]),
        ]
    )
    app.add_middleware(SharedSecretAuthMiddleware, secret=secret)
    return app


_SECRET = {MCP_AUTH_HEADER: "s3cret"}


@pytest.mark.parametrize(
    ("secret", "method", "path", "headers", "statuses", "body"),
    [
        (None, "POST", "/mcp", {}, {200}, "tool result"),
        ("s3cret", "POST", "/mcp", {}, {401}, None),
        ("s3cret", "POST", "/mcp", {MCP_AUTH_HEADER: "wrong"}, {401}, None),
        ("s3cret", "POST", "/mcp", _SECRET, {200}, "tool result"),
        # A host path must not exempt an unauthenticated tool call.
        ("s3cret", "POST", "/mcp", {"Host": "example.com/#"}, {400, 401}, None),
        ("s3cret", "POST", "/mcp", {"Host": "example.com/?"}, {400, 401}, None),
        ("s3cret", "GET", "/", {}, {200}, "status"),
    ],
)
def test_shared_secret_guards_tool_calls_(
    secret: str | None,
    method: str,
    path: str,
    headers: dict[str, str],
    statuses: set[int],
    body: str | None,
) -> None:
    response = TestClient(_make_app(secret)).request(method, path, headers=headers)

    assert response.status_code in statuses
    if body is not None:
        assert response.text == body
