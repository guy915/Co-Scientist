from __future__ import annotations

import ssl
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import mcp_server.entrez as entrez_rate_limit
import pytest
from Bio import Entrez
from mcp_server import entrez


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


def _capture_requests(monkeypatch: pytest.MonkeyPatch) -> list[Request]:
    requests: list[Request] = []

    def capture(request: Request) -> Request:
        requests.append(request)
        return request

    monkeypatch.setattr(Entrez, "email", "offline@example.invalid")
    monkeypatch.setattr(Entrez, "api_key", None)
    monkeypatch.setattr(Entrez, "_open", capture)
    return requests


def _request_params(request: Request) -> dict[str, list[str]]:
    data = request.data
    if data is None:
        encoded = urlsplit(request.full_url).query
    else:
        assert isinstance(data, bytes)
        encoded = data.decode("utf-8")
    return parse_qs(encoded)


def test_requests_keep_the_service_key(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = _capture_requests(monkeypatch)
    monkeypatch.setattr(Entrez, "api_key", "service-held-key")
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
    entrez_rate_limit.entrez_call(Entrez.esearch, db="pubmed", term="EGFR resistance")
    assert entrez_rate_limit._request_interval() == entrez_rate_limit._INTERVAL_WITH_API_KEY
    (request,) = requests
    assert "api_key=service-held-key" in request.full_url + str(request.data or "")


_TEST_INTERVAL = 0.05


@pytest.fixture
def paced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entrez_rate_limit, "_request_interval", lambda: _TEST_INTERVAL)
    monkeypatch.setattr(entrez_rate_limit, "_next_slot", 0.0)
    # Consume the overdue slot before measuring; interpreter lag otherwise
    # shortens the first gap.
    entrez_rate_limit.entrez_call(lambda **_kwargs: None)


@pytest.mark.usefixtures("paced")
class TestEntrezRateLimit:
    def test_concurrent_callers_do_not_burst(self) -> None:
        """Biopython's unlocked previous-request timestamp lets concurrent
        threads burst together."""
        issued: list[float] = []
        guard = threading.Lock()

        def request(**_kwargs: Any) -> None:
            with guard:
                issued.append(time.monotonic())

        threads = [
            threading.Thread(target=lambda: entrez_rate_limit.entrez_call(request))
            for _ in range(6)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Measure the whole span: descheduling can squeeze an adjacent gap but
        # cannot fake a burst-free span.
        assert len(issued) == 6
        span = max(issued) - min(issued)
        assert span >= 5 * _TEST_INTERVAL * 0.9, span

    def test_the_wait_does_not_hold_the_lock(self) -> None:
        """Pacing bounds departure times; holding a lock over I/O serializes
        independent responses."""
        started = threading.Event()
        release = threading.Event()

        def slow(**_kwargs: Any) -> None:
            started.set()
            release.wait(timeout=5)

        slow_thread = threading.Thread(target=lambda: entrez_rate_limit.entrez_call(slow))
        slow_thread.start()
        assert started.wait(timeout=5)

        quick_done = threading.Event()

        def quick() -> None:
            entrez_rate_limit.entrez_call(lambda **_kwargs: None)
            quick_done.set()

        threading.Thread(target=quick).start()

        assert quick_done.wait(timeout=5), "second caller waited on the first"
        release.set()
        slow_thread.join()


_IDS = [str(value) for value in range(1_000_000, 1_000_201)]


@pytest.mark.parametrize(
    ("request_ids", "method"),
    [(["101", "202", "303"], "GET"), (_IDS, "POST")],
)
def test_efetch_sends_the_id_list_as_one_comma_separated_value(
    monkeypatch: pytest.MonkeyPatch,
    request_ids: list[str],
    method: str,
) -> None:
    requests = _capture_requests(monkeypatch)

    Entrez.efetch(db="pubmed", id=request_ids, retmode="xml")

    (request,) = requests
    assert request.get_method() == method
    assert _request_params(request)["id"] == [",".join(request_ids)]


@pytest.mark.parametrize(
    ("request_ids", "method"),
    [(["101", "202", "303"], "GET"), (_IDS, "POST")],
)
def test_elink_sends_each_id_as_a_separate_parameter(
    monkeypatch: pytest.MonkeyPatch, request_ids: list[str], method: str
) -> None:
    requests = _capture_requests(monkeypatch)

    Entrez.elink(dbfrom="pubmed", db="pmc", linkname="pubmed_pmc", id=request_ids)

    (request,) = requests
    params = _request_params(request)
    assert request.get_method() == method
    assert params["id"] == request_ids
    assert params["linkname"] == ["pubmed_pmc"]
