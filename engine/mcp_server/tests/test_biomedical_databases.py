"""Tests for normalized ChEMBL and UniProt MCP retrieval tools."""

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
