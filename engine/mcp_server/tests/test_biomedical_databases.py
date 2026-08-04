"""Tests for normalized ChEMBL and UniProt MCP retrieval tools."""

import logging
from typing import Any, ClassVar

import httpx
import pytest
from mcp_server.tools import biomedical_databases


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        """Represent a successful response."""

    def json(self) -> dict[str, Any]:
        """Return the fixture payload."""
        return self._payload


class _Client:
    payload: ClassVar[dict[str, Any]] = {}

    def __init__(self, **_: Any) -> None:
        pass

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def get(self, *_: Any, **__: Any) -> _Response:
        return _Response(self.payload)


class _FailingClient:
    """A canned httpx.AsyncClient that raises instead of responding.

    Stands in for a transient EBI outage: a connection failure raised
    directly out of ``client.get``, before any response exists.
    """

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def __aenter__(self) -> "_FailingClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def get(self, *_: Any, **__: Any) -> _Response:
        raise self._error


class _ErrorStatusClient:
    """A canned httpx.AsyncClient returning a real non-2xx response.

    Uses a genuine ``httpx.Response`` (rather than the local ``_Response``
    fake) so ``raise_for_status`` raises the real ``httpx.HTTPStatusError``
    a 503 from EBI during an outage would produce.
    """

    def __init__(self, status_code: int) -> None:
        self._status_code = status_code

    async def __aenter__(self) -> "_ErrorStatusClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def get(self, *_: Any, **__: Any) -> httpx.Response:
        return httpx.Response(
            self._status_code,
            request=httpx.Request("GET", "https://example.test"),
        )


async def test_search_chembl_normalizes_molecule_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Client.payload = {
        "molecules": [
            {
                "molecule_chembl_id": "CHEMBL25",
                "pref_name": "ASPIRIN",
                "molecule_type": "Small molecule",
                "max_phase": 4,
                "first_approval": 1950,
            }
        ]
    }
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    result = await biomedical_databases.search_chembl("aspirin")
    assert result["source"] == "ChEMBL"
    assert result["records"][0]["chembl_id"] == "CHEMBL25"


async def test_search_uniprot_returns_reviewed_functional_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Client.payload = {
        "results": [
            {
                "primaryAccession": "P00533",
                "genes": [{"geneName": {"value": "EGFR"}}],
                "proteinDescription": {
                    "recommendedName": {"fullName": {"value": "EGFR"}}
                },
                "organism": {"scientificName": "Homo sapiens"},
                "comments": [
                    {"commentType": "FUNCTION", "texts": [{"value": "Kinase."}]}
                ],
            }
        ]
    }
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    result = await biomedical_databases.search_uniprot("EGFR")
    assert result["source"] == "UniProtKB/Swiss-Prot"
    assert result["records"][0]["gene"] == "EGFR"
    assert result["records"][0]["functions"] == ["Kinase."]


async def test_search_chembl_degrades_on_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_: _FailingClient(httpx.ConnectError("connection refused")),
    )
    with caplog.at_level(logging.WARNING):
        result = await biomedical_databases.search_chembl("aspirin")
    # A transient outage must degrade to the same shape as a genuine
    # zero-hit search, not raise -- every other registered tool does this.
    assert result == {"source": "ChEMBL", "query": "aspirin", "records": []}
    assert "ChEMBL search failed for 'aspirin'" in caplog.text


async def test_search_uniprot_degrades_on_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_: _FailingClient(httpx.ConnectError("connection refused")),
    )
    with caplog.at_level(logging.WARNING):
        result = await biomedical_databases.search_uniprot("EGFR")
    assert result == {
        "source": "UniProtKB/Swiss-Prot",
        "query": "EGFR",
        "records": [],
    }
    assert "UniProt search failed for 'EGFR'" in caplog.text


async def test_search_chembl_degrades_on_http_status_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **_: _ErrorStatusClient(503)
    )
    result = await biomedical_databases.search_chembl("aspirin")
    assert result == {"source": "ChEMBL", "query": "aspirin", "records": []}


async def test_search_uniprot_degrades_on_http_status_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **_: _ErrorStatusClient(503)
    )
    result = await biomedical_databases.search_uniprot("EGFR")
    assert result == {
        "source": "UniProtKB/Swiss-Prot",
        "query": "EGFR",
        "records": [],
    }
