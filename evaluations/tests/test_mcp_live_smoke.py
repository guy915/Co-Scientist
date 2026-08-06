"""Unit tests for the MCP live-smoke check logic (N34).

These monkeypatch ``httpx.get``/``httpx.post`` to exercise the pass/fail
*logic* of each check offline -- the live calls themselves
(``python -m evaluations.mcp_live_smoke``) stay a by-hand run, never wired
into CI.
"""

from __future__ import annotations

import httpx
import pytest

from evaluations import mcp_live_smoke


def _fake_response(status_code: int, json_body: object) -> httpx.Response:
    return httpx.Response(
        status_code, json=json_body, request=httpx.Request("GET", "https://x")
    )


def test_pubmed_contract_ok_on_populated_idlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: _fake_response(
            200, {"esearchresult": {"idlist": ["1", "2"]}}
        ),
    )
    result = mcp_live_smoke.check_pubmed_contract()
    assert result.ok


def test_pubmed_contract_fails_on_empty_idlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: _fake_response(200, {"esearchresult": {"idlist": []}}),
    )
    result = mcp_live_smoke.check_pubmed_contract()
    assert not result.ok


def test_pubmed_contract_fails_on_missing_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: _fake_response(200, {"unexpected": {}})
    )
    result = mcp_live_smoke.check_pubmed_contract()
    assert not result.ok


def test_pubmed_burst_ok_on_well_formed_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("evaluations.mcp_live_smoke.time.sleep", lambda _: None)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_response(429, {}))
    result = mcp_live_smoke.check_pubmed_burst_is_handled()
    assert result.ok


def test_pubmed_burst_fails_on_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("evaluations.mcp_live_smoke.time.sleep", lambda _: None)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_response(500, {}))
    result = mcp_live_smoke.check_pubmed_burst_is_handled()
    assert not result.ok


def test_openalex_contract_ok_on_populated_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: _fake_response(
            200, {"results": [{"id": "https://openalex.org/W1"}]}
        ),
    )
    result = mcp_live_smoke.check_openalex_contract()
    assert result.ok


def test_openalex_contract_fails_when_id_is_not_a_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: _fake_response(200, {"results": [{"id": 123}]}),
    )
    result = mcp_live_smoke.check_openalex_contract()
    assert not result.ok


def test_indra_contract_ok_on_shaped_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: _fake_response(
            200, [{"data": {"db_ns": "HGNC", "db_id": "1"}}]
        ),
    )
    result = mcp_live_smoke.check_indra_contract()
    assert result.ok


def test_indra_contract_fails_on_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _fake_response(200, []))
    result = mcp_live_smoke.check_indra_contract()
    assert not result.ok


def test_main_returns_nonzero_when_any_check_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp_live_smoke,
        "run",
        lambda: [mcp_live_smoke.CheckResult("pubmed_contract", False, "boom")],
    )
    assert mcp_live_smoke.main() == 1


def test_main_returns_zero_when_every_check_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp_live_smoke,
        "run",
        lambda: [mcp_live_smoke.CheckResult("pubmed_contract", True, "ok")],
    )
    assert mcp_live_smoke.main() == 0
