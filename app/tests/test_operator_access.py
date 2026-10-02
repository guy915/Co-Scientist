"""Shared operator access policy and its request trust boundary."""

import pytest
from fastapi import Request

from app.config import settings
from app.operator_access import is_operator


@pytest.mark.parametrize(
    ("configured_token", "supplied_token", "host", "expected"),
    [
        ("", "", "127.0.0.1", True),
        ("", "", "::1", True),
        ("", "", "localhost", True),
        ("", "", "127.0.0.2", False),
        ("", "", "remote.example", False),
        ("", "", None, False),
        ("", "admin-token", "remote.example", False),
        ("admin-token", "admin-token", "remote.example", True),
        ("admin-token", "admin-token", None, True),
        ("admin-token", "wrong-token", "remote.example", False),
        ("admin-token", "", "remote.example", False),
        ("admin-token", "wrong-token", "127.0.0.1", True),
        ("admin-token", "", "::1", True),
    ],
)
def test_operator_access(
    monkeypatch: pytest.MonkeyPatch,
    configured_token: str,
    supplied_token: str,
    host: str | None,
    expected: bool,
) -> None:
    monkeypatch.setattr(settings, "logs_admin_token", configured_token)
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-logs-token", supplied_token.encode())],
            "client": (host, 50000) if host else None,
        }
    )

    assert is_operator(request) is expected


@pytest.mark.parametrize(
    "header",
    [
        (b"host", b"localhost"),
        (b"x-forwarded-for", b"127.0.0.1"),
        (b"forwarded", b"for=127.0.0.1;host=localhost"),
    ],
)
def test_request_headers_cannot_supply_loopback_address(
    monkeypatch: pytest.MonkeyPatch, header: tuple[bytes, bytes]
) -> None:
    monkeypatch.setattr(settings, "logs_admin_token", "")
    request = Request(
        {
            "type": "http",
            "headers": [header],
            "client": ("remote.example", 50000),
        }
    )

    assert is_operator(request) is False
