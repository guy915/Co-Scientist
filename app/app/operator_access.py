"""Shared operator access policy for logs, diagnostics, and API docs."""

import hmac

from fastapi import Request

from app.config import settings

# Direct loopback callers are already inside the local trust boundary.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def is_operator(request: Request) -> bool:
    # Host and forwarding headers must never establish operator access.
    token = settings.logs_admin_token
    if token:
        supplied = request.headers.get("X-Logs-Token", "")
        if supplied and hmac.compare_digest(supplied, token):
            return True
    host = request.client.host if request.client else ""
    return host in _LOOPBACK_HOSTS
