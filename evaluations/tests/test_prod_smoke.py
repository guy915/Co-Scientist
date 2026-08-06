"""Unit tests for the prod-smoke check logic (N33).

These run fully offline against ``httpx.MockTransport`` -- they exercise the
pass/fail *logic* of each check, not a live deployment (that stays a
by-hand run: ``python -m evaluations.prod_smoke``, never wired into CI).
"""

from __future__ import annotations

import httpx
import pytest

from evaluations import prod_smoke


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(base_url="https://smoke.test", transport=handler)


def test_check_health_ok_on_healthy_status() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"status": "healthy"})
    )
    result = prod_smoke.check_health(_client(transport))
    assert result.ok


def test_check_health_fails_on_unhealthy_status() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"status": "unhealthy"})
    )
    result = prod_smoke.check_health(_client(transport))
    assert not result.ok


def test_check_health_fails_on_non_200() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(503))
    result = prod_smoke.check_health(_client(transport))
    assert not result.ok


def test_check_status_probes_is_informational_never_blocking() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json={
                "mcp_available": False,
                "email_notifications_available": False,
                "llm_backend": "real",
            },
        )
    )
    result = prod_smoke.check_status_probes(_client(transport))
    assert result.ok
    assert not result.blocking


def test_check_ownership_isolation_ok_on_404() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(404))
    result = prod_smoke.check_ownership_isolation(_client(transport))
    assert result.ok


def test_check_ownership_isolation_fails_when_run_is_readable() -> None:
    """A random unowned run id must never resolve to 200.

    That would be an ownership leak, not a smoke pass.
    """
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"id": "leaked"})
    )
    result = prod_smoke.check_ownership_isolation(_client(transport))
    assert not result.ok


def test_check_cors_untrusted_origin_ok_when_not_echoed() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    result = prod_smoke.check_cors_untrusted_origin(_client(transport))
    assert result.ok


def test_check_cors_untrusted_origin_fails_when_echoed() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            headers={
                "Access-Control-Allow-Origin": prod_smoke._UNTRUSTED_ORIGIN
            },
        )
    )
    result = prod_smoke.check_cors_untrusted_origin(_client(transport))
    assert not result.ok


def test_check_cors_untrusted_origin_fails_on_wildcard() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200, headers={"Access-Control-Allow-Origin": "*"}
        )
    )
    result = prod_smoke.check_cors_untrusted_origin(_client(transport))
    assert not result.ok


def test_check_sanitized_share_404_ok_on_clean_404() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(404, json={"detail": "not found"})
    )
    result = prod_smoke.check_sanitized_share_404(_client(transport))
    assert result.ok


def test_check_sanitized_share_404_fails_when_body_leaks_internals() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            404, text="Traceback (most recent call last): ... /Users/x/app"
        )
    )
    result = prod_smoke.check_sanitized_share_404(_client(transport))
    assert not result.ok


def test_check_sanitized_share_404_fails_on_non_404() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    result = prod_smoke.check_sanitized_share_404(_client(transport))
    assert not result.ok


def test_run_invokes_every_check_against_the_given_base_url() -> None:
    seen_urls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_urls.append(str(req.url))
        if "/health" in str(req.url):
            return httpx.Response(200, json={"status": "healthy"})
        if "/status" in str(req.url):
            return httpx.Response(200, json={})
        if "/api/shared/" in str(req.url):
            return httpx.Response(404)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    results = prod_smoke.run("https://smoke.test", transport=transport)

    assert {r.name for r in results} == {
        "health",
        "status_probes",
        "ownership_isolation",
        "cors_untrusted_origin",
        "sanitized_share_404",
    }
    assert len(seen_urls) == 5


def test_main_returns_nonzero_when_a_blocking_check_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        prod_smoke,
        "run",
        lambda base_url: [prod_smoke.CheckResult("health", False, "boom")],
    )
    assert prod_smoke.main(["--base-url", "https://smoke.test"]) == 1


def test_main_returns_zero_when_only_informational_checks_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        prod_smoke,
        "run",
        lambda base_url: [
            prod_smoke.CheckResult(
                "status_probes", False, "meh", blocking=False
            )
        ],
    )
    assert prod_smoke.main(["--base-url", "https://smoke.test"]) == 0
