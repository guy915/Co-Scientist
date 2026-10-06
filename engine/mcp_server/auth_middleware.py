"""Shared secrets add a control beyond network placement; unset preserves
unauthenticated deployments.
"""

import hmac
import os

from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from mcp_server.campaign import scoped_campaign_request

MCP_SHARED_SECRET_ENV = "COSCIENTIST_MCP_SHARED_SECRET"

MCP_AUTH_HEADER = "X-MCP-Shared-Secret"

MCP_CAMPAIGN_HEADER = "X-CoScientist-Campaign"

# Keep GET / public for platform health probes.
_EXEMPT_PATHS = frozenset({"/"})


class SharedSecretAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, secret: str | None) -> None:
        super().__init__(app)
        self._secret = secret or None

    def _secret_matches(self, request: Request) -> bool:
        """Compare presented credentials without a prefix-dependent check."""
        presented = request.headers.get(MCP_AUTH_HEADER, "")
        return bool(self._secret) and hmac.compare_digest(
            presented.encode(), (self._secret or "").encode()
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        campaign_value = request.headers.get(MCP_CAMPAIGN_HEADER)
        campaign = campaign_value == "1"
        if campaign_value is not None and not campaign:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        # Plain health checks stay open. Asking that same route to attest a
        # policy is privileged and therefore requires the configured secret.
        if campaign and not self._secret_matches(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        # Authorize the ASGI path the router receives. URL reconstruction
        # includes the caller's Host header and is not an auth boundary.
        requires_check = self._secret and request.scope["path"] not in _EXEMPT_PATHS
        if requires_check and not self._secret_matches(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        with scoped_campaign_request(campaign):
            return await call_next(request)


def resolve_shared_secret() -> str | None:
    return os.environ.get(MCP_SHARED_SECRET_ENV) or None
