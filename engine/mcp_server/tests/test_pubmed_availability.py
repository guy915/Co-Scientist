"""Availability reflects a real Entrez response, not contact configuration."""

from io import BytesIO
from urllib.error import URLError

import pytest
from Bio import Entrez
from mcp_server.tools.lit_review.search_pubmed import check_pubmed_available


@pytest.mark.parametrize("reachable", [True, False])
def test_anonymous_pubmed_availability_queries_service(
    monkeypatch: pytest.MonkeyPatch, reachable: bool
) -> None:
    monkeypatch.delenv("ENTREZ_EMAIL", raising=False)
    monkeypatch.delenv("ENTREZ_API_KEY", raising=False)
    monkeypatch.setattr(Entrez, "email", None)
    monkeypatch.setattr(Entrez, "api_key", None)
    called: list[dict[str, object]] = []

    def esearch(**kwargs: object) -> BytesIO:
        called.append(kwargs)
        if not reachable:
            raise URLError("test service unavailable")
        return BytesIO(
            b'<?xml version="1.0" encoding="UTF-8" ?>'
            b"<!DOCTYPE eSearchResult PUBLIC "
            b'"-//NLM//DTD esearch 20060628//EN" '
            b'"https://eutils.ncbi.nlm.nih.gov/eutils/dtd/20060628/esearch.dtd">'
            b"<eSearchResult><IdList><Id>22745249</Id></IdList></eSearchResult>"
        )

    monkeypatch.setattr(Entrez, "esearch", esearch)
    assert check_pubmed_available() == ("true" if reachable else "false")
    assert len(called) == 1
