import hmac

from fastapi import Request

from co_scientist.core.config import settings

# Direct loopback peers are inside the local trust boundary.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def has_admin_token(request: Request) -> bool:
    token = settings.logs_admin_token
    supplied = request.headers.get("X-Logs-Token", "")
    return bool(token and supplied and hmac.compare_digest(supplied.encode(), token.encode()))


def is_operator(request: Request) -> bool:
    # Host and forwarding headers never establish operator access.
    if has_admin_token(request):
        return True
    host = request.client.host if request.client else ""
    return host in _LOOPBACK_HOSTS
