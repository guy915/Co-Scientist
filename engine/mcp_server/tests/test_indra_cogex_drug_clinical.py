"""Tests for drug target/indication/side-effect and clinical trial tools."""

from typing import Any

import httpx
import pytest
from mcp_server.tools.indra_cogex.drug_clinical import (
    query_clinical_trials,
    query_drug_info,
)


class _StubResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        """Represent a 2xx response: never raises."""

    def json(self) -> Any:
        """Return the fixture payload."""
        return self._payload


class _StubClient:
    def __init__(
        self, payload: Any = None, error: Exception | None = None
    ) -> None:
        self._payload = payload
        self._error = error
        self.calls: list[tuple[str, Any]] = []

    async def __aenter__(self) -> "_StubClient":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def post(self, url: str, json: Any = None) -> _StubResponse:
        self.calls.append((url, json))
        if self._error is not None:
            raise self._error
        return _StubResponse(self._payload)


def _stub(monkeypatch: pytest.MonkeyPatch, payload: Any) -> _StubClient:
    client = _StubClient(payload=payload)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)
    return client


def _stub_unreachable(monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    client = _StubClient(error=RuntimeError(message))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)


# --- query_drug_info: all four query_type branches share one dispatch ---
# table (_DRUG_ENDPOINTS in the source), so they are parametrized here too.
# The expected mapping is written out by hand rather than imported from
# that table, so a change to the table itself still has something to check
# it against.


@pytest.mark.parametrize(
    "query_type,endpoint,param_name,result_key",
    [
        ("targets", "/api/get_targets_for_drug", "drug", "targets"),
        (
            "drugs_for_target",
            "/api/get_drugs_for_target",
            "target",
            "drugs",
        ),
        (
            "indications",
            "/api/get_indications_for_drug",
            "molecule",
            "indications",
        ),
        (
            "side_effects",
            "/api/get_side_effects_for_drug",
            "drug",
            "side_effects",
        ),
    ],
)
async def test_drug_info_success(
    query_type: str,
    endpoint: str,
    param_name: str,
    result_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _stub(monkeypatch, [{"id": "X"}])

    result = await query_drug_info("CHEBI:CHEBI:27690", query_type=query_type)

    assert result[result_key] == [{"id": "X"}]
    assert result[f"total_{result_key}"] == 1
    call_url, call_payload = client.calls[0]
    assert call_url.endswith(endpoint)
    assert param_name in call_payload


async def test_drug_info_rejects_invalid_query_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_unreachable(monkeypatch, "must not reach the network")

    result = await query_drug_info("CHEBI:CHEBI:27690", query_type="bogus")

    assert result == {
        "error": (
            "invalid query_type 'bogus', use: targets, drugs_for_target, "
            "indications, side_effects"
        ),
        "query": {
            "identifier": "CHEBI:CHEBI:27690",
            "query_type": "bogus",
        },
    }


# --- query_clinical_trials: disease vs drug -------------------------------


@pytest.mark.parametrize(
    "entity_type,endpoint,param_name",
    [
        ("disease", "/api/get_trials_for_disease", "disease"),
        ("drug", "/api/get_trials_for_drug", "drug"),
    ],
)
async def test_clinical_trials_success(
    entity_type: str,
    endpoint: str,
    param_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _stub(monkeypatch, [{"nct_id": "NCT1"}])

    result = await query_clinical_trials(
        "MESH:D000544", entity_type=entity_type
    )

    assert result["trials"] == [{"nct_id": "NCT1"}]
    assert result["total_trials"] == 1
    call_url, call_payload = client.calls[0]
    assert call_url.endswith(endpoint)
    assert param_name in call_payload


async def test_clinical_trials_rejects_invalid_entity_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_unreachable(monkeypatch, "must not reach the network")

    result = await query_clinical_trials("MESH:D000544", entity_type="bogus")

    assert result == {
        "error": "invalid entity_type 'bogus', use 'disease' or 'drug'",
        "query": {"identifier": "MESH:D000544", "entity_type": "bogus"},
    }
