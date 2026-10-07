import hmac

from co_scientist.core.config import settings
from fastapi import Request

# Direct loopback peers are inside the local trust boundary.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def is_operator(request: Request) -> bool:
    # Host and forwarding headers never establish operator access.
    token = settings.logs_admin_token
    if token:
        supplied = request.headers.get("X-Logs-Token", "")
        if supplied and hmac.compare_digest(supplied, token):
            return True
    host = request.client.host if request.client else ""
    return host in _LOOPBACK_HOSTS
