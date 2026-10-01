"""Offline checks for Biopython's multi-ID EFetch and ELink encoding."""

from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest
from Bio import Entrez


def _capture_requests(monkeypatch: pytest.MonkeyPatch) -> list[Request]:
    """Intercepts Biopython after request construction and before I/O."""
    requests: list[Request] = []

    def capture(request: Request) -> Request:
        requests.append(request)
        return request

    monkeypatch.setattr(Entrez, "email", "offline@example.invalid")
    monkeypatch.setattr(Entrez, "api_key", None)
    monkeypatch.setattr(Entrez, "_open", capture)
    return requests


def _request_params(request: Request) -> dict[str, list[str]]:
    """Reads the encoded query string or POST body from a Request."""
    data = request.data
    if data is None:
        encoded = urlsplit(request.full_url).query
    else:
        assert isinstance(data, bytes)
        encoded = data.decode("utf-8")
    return parse_qs(encoded)


def test_efetch_get_encodes_id_list_as_one_comma_separated_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _capture_requests(monkeypatch)

    Entrez.efetch(db="pubmed", id=["101", "202", "303"], retmode="xml")

    assert len(requests) == 1
    request = requests[0]
    assert request.get_method() == "GET"
    assert _request_params(request)["id"] == ["101,202,303"]


def test_elink_get_keeps_each_id_as_a_separate_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _capture_requests(monkeypatch)

    Entrez.elink(
        dbfrom="pubmed",
        db="pmc",
        linkname="pubmed_pmc",
        id=["101", "202", "303"],
    )

    assert len(requests) == 1
    request = requests[0]
    assert request.get_method() == "GET"
    params = _request_params(request)
    assert params["id"] == ["101", "202", "303"]
    assert params["dbfrom"] == ["pubmed"]
    assert params["db"] == ["pmc"]
    assert params["linkname"] == ["pubmed_pmc"]


def test_efetch_post_keeps_list_in_one_comma_separated_form_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _capture_requests(monkeypatch)
    ids = [str(value) for value in range(1_000_000, 1_000_201)]

    Entrez.efetch(db="pubmed", id=ids, retmode="xml")

    assert len(requests) == 1
    request = requests[0]
    assert request.get_method() == "POST"
    assert _request_params(request)["id"] == [",".join(ids)]


def test_elink_post_keeps_ids_as_repeated_form_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _capture_requests(monkeypatch)
    ids = [str(value) for value in range(1_000_000, 1_000_201)]

    Entrez.elink(
        dbfrom="pubmed",
        db="pmc",
        linkname="pubmed_pmc",
        id=ids,
    )

    assert len(requests) == 1
    request = requests[0]
    assert request.get_method() == "POST"
    params = _request_params(request)
    assert params["id"] == ids
    assert params["dbfrom"] == ["pubmed"]
    assert params["db"] == ["pmc"]
    assert params["linkname"] == ["pubmed_pmc"]
