"""Shared-secret authentication for the MCP server.

This server has no auth of its own -- historically it relied entirely on
network placement (Railway's private network in production, `localhost` in
dev) to keep it from being called by anyone but the engine's MCP client. That
is one control, not two: dev Compose also publishes this port to the host,
and `read_url` can fetch arbitrary URLs, so a caller that merely reaches the
port can use it.

This module adds an inner control: every request other than the plain status
route must carry a header matching ``COSCIENTIST_MCP_SHARED_SECRET``. The
variable is optional and unset by default -- this is a reference server the
user deploys by hand, and a token that hard-fails on rollout would take
production down -- so an unset variable reproduces exactly today's
behaviour: no check is made. Set the same value on the `api` and `mcp`
services to turn the check on; see AGENTS.md's deployment section and
`.env.example`.
"""

import os

from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

MCP_SHARED_SECRET_ENV = "COSCIENTIST_MCP_SHARED_SECRET"
"""Env var carrying the shared secret. Unset disables the check entirely."""

MCP_AUTH_HEADER = "X-MCP-Shared-Secret"
"""HTTP header the client must send once a shared secret is configured."""

# The plain status route stays open even when a secret is configured: it is
# what Compose's own healthcheck and `curl http://.../` probe (see AGENTS.md),
# and it discloses nothing an unauthenticated caller could act on that N14
# does not already track separately.
_EXEMPT_PATHS = frozenset({"/"})


class SharedSecretAuthMiddleware(BaseHTTPMiddleware):
    """Rejects requests missing the configured shared-secret header.

    A no-op when ``secret`` is falsy, so the middleware can always be
    installed and the environment variable alone decides whether it does
    anything.
    """

    def __init__(self, app: ASGIApp, secret: str | None) -> None:
        """Initializes the middleware.

        Args:
            app: The ASGI application to wrap.
            secret: The expected header value, or None/empty to disable the
                check.
        """
        super().__init__(app)
        self._secret = secret or None

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Checks the shared-secret header before delegating downstream.

        Args:
            request: The incoming request.
            call_next: The next handler in the middleware chain.

        Returns:
            A 401 JSON response when a secret is configured and the request
            fails to present it; otherwise the downstream response.
        """
        requires_check = self._secret and request.url.path not in _EXEMPT_PATHS
        if (
            requires_check
            and request.headers.get(MCP_AUTH_HEADER) != self._secret
        ):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def resolve_shared_secret() -> str | None:
    """Return the configured shared secret, or None if unset/empty.

    Returns:
        The value of ``COSCIENTIST_MCP_SHARED_SECRET``, or None when the
        variable is unset or empty -- callers treat both as "auth disabled".
    """
    return os.environ.get(MCP_SHARED_SECRET_ENV) or None
