"""Campaign PubMed requests keep credentials isolated and TLS verified."""

from __future__ import annotations

import ssl
from typing import Any

import pytest
from Bio import Entrez
from mcp_server import entrez, entrez_rate_limit
from mcp_server.campaign import scoped_campaign_request


def test_entrez_default_preserves_certificate_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entrez, "_entrez_initialized", False)
    monkeypatch.delenv("DISABLE_SSL_VERIFY", raising=False)
    original = ssl._create_default_https_context

    entrez.initialize_entrez()

    assert ssl._create_default_https_context is original


def test_entrez_rejects_insecure_tls_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entrez, "_entrez_initialized", False)
    monkeypatch.setenv("DISABLE_SSL_VERIFY", "true")
    original = ssl._create_default_https_context

    with pytest.raises(RuntimeError, match="TLS verification"):
        entrez.initialize_entrez()

    assert ssl._create_default_https_context is original
    assert entrez._entrez_initialized is False


def test_campaign_request_omits_shared_entrez_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Entrez, "api_key", "service-held-key")
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
    captured: dict[str, Any] = {}

    def open_request(request: Any) -> object:
        captured["url"] = request.full_url
        captured["body"] = request.data
        return object()

    monkeypatch.setattr(Entrez, "_open", open_request)
    with scoped_campaign_request(True):
        entrez_rate_limit.entrez_call(
            Entrez.esearch,
            db="pubmed",
            term="EGFR resistance",
            api_key="caller-override",
        )
        assert entrez_rate_limit._request_interval() == (
            entrez_rate_limit._INTERVAL_WITHOUT_API_KEY
        )

    wire = captured["url"].encode() + (captured["body"] or b"")
    assert b"api_key=" not in wire
    assert b"service-held-key" not in wire
    assert b"caller-override" not in wire


def test_standard_request_keeps_its_entrez_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Entrez, "api_key", "service-held-key")
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
    captured: dict[str, Any] = {}

    def open_request(request: Any) -> object:
        captured["url"] = request.full_url
        captured["body"] = request.data
        return object()

    monkeypatch.setattr(Entrez, "_open", open_request)
    with scoped_campaign_request(False):
        entrez_rate_limit.entrez_call(
            Entrez.esearch, db="pubmed", term="EGFR resistance"
        )
        assert entrez_rate_limit._request_interval() == (
            entrez_rate_limit._INTERVAL_WITH_API_KEY
        )

    wire = captured["url"].encode() + (captured["body"] or b"")
    assert b"api_key=service-held-key" in wire
