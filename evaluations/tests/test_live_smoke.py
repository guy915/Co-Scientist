from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from evaluations import mcp_live_smoke, prod_smoke

_ORIGIN = {"Access-Control-Allow-Origin": prod_smoke._UNTRUSTED_ORIGIN}
_LEAK = "Traceback (most recent call last): ... /Users/x/app"


@pytest.mark.parametrize(
    ("check", "response", "ok"),
    [
        ("check_health", httpx.Response(200, json={"status": "healthy"}), True),
        ("check_health", httpx.Response(200, json={"status": "x"}), False),
        ("check_health", httpx.Response(503), False),
        ("check_ownership_isolation", httpx.Response(404), True),
        (
            "check_ownership_isolation",
            httpx.Response(200, json={"id": 1}),
            False,
        ),
        ("check_cors_untrusted_origin", httpx.Response(200), True),
        (
            "check_cors_untrusted_origin",
            httpx.Response(200, headers=_ORIGIN),
            False,
        ),
        (
            "check_cors_untrusted_origin",
            httpx.Response(200, headers={"Access-Control-Allow-Origin": "*"}),
            False,
        ),
        ("check_sanitized_share_404", httpx.Response(404, json={}), True),
        ("check_sanitized_share_404", httpx.Response(404, text=_LEAK), False),
        ("check_sanitized_share_404", httpx.Response(500), False),
    ],
)
def test_prod_smoke_checks_judge_the_response(
    check: str, response: httpx.Response, ok: bool
) -> None:
    client = httpx.Client(
        base_url="https://smoke.test",
        transport=httpx.MockTransport(lambda request: response),
    )
    assert getattr(prod_smoke, check)(client).ok is ok


def test_prod_smoke_runs_every_check_and_status_probes_never_block() -> None:
    transport = httpx.MockTransport(
        lambda request: (
            httpx.Response(200, json={"status": "healthy", "mcp_available": False})
            if "/health" in str(request.url) or "/status" in str(request.url)
            else httpx.Response(404)
        )
    )

    results = prod_smoke.run("https://smoke.test", transport=transport)

    assert {r.name for r in results} == {
        "health",
        "status_probes",
        "ownership_isolation",
        "cors_untrusted_origin",
        "sanitized_share_404",
    }
    probes = next(r for r in results if r.name == "status_probes")
    assert probes.ok and not probes.blocking


@pytest.mark.parametrize(("blocking", "exit_code"), [(True, 1), (False, 0)])
def test_main_fails_only_for_blocking_checks(
    monkeypatch: pytest.MonkeyPatch, blocking: bool, exit_code: int
) -> None:
    failed = prod_smoke.CheckResult("probe", False, "boom", blocking=blocking)
    monkeypatch.setattr(prod_smoke, "run", lambda base_url: [failed])
    assert prod_smoke.main(["--base-url", "https://smoke.test"]) == exit_code


def test_mcp_main_fails_when_any_check_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = mcp_live_smoke.CheckResult("probe", False, "boom")
    monkeypatch.setattr(mcp_live_smoke, "run", lambda: [failed])
    assert mcp_live_smoke.main() == 1


def _reply(status: int, body: object) -> Callable[..., httpx.Response]:
    response = httpx.Response(status, json=body, request=httpx.Request("GET", "https://x"))
    return lambda *args, **kwargs: response


@pytest.mark.parametrize(
    ("check", "status", "body", "ok"),
    [
        (
            "pubmed_contract",
            200,
            {"esearchresult": {"idlist": ["1"]}},
            True,
        ),
        (
            "pubmed_contract",
            200,
            {"esearchresult": {"idlist": []}},
            False,
        ),
        ("pubmed_contract", 200, {"unexpected": {}}, False),
        ("pubmed_burst_is_handled", 429, {}, True),
        ("pubmed_burst_is_handled", 500, {}, False),
        ("openalex_contract", 200, {"results": [{"id": "W1"}]}, True),
        ("openalex_contract", 200, {"results": [{"id": 123}]}, False),
        (
            "indra_contract",
            200,
            [{"data": {"db_ns": "H", "db_id": "1"}}],
            True,
        ),
        ("indra_contract", 200, [], False),
    ],
)
def test_mcp_contract_checks_judge_the_upstream_response(
    monkeypatch: pytest.MonkeyPatch,
    check: str,
    status: int,
    body: object,
    ok: bool,
) -> None:
    monkeypatch.setattr("evaluations.mcp_live_smoke.time.sleep", lambda _: None)
    method = "post" if check == "indra_contract" else "get"
    monkeypatch.setattr(httpx, method, _reply(status, body))
    assert getattr(mcp_live_smoke, f"check_{check}")().ok is ok
