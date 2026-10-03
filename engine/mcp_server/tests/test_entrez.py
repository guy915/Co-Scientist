"""Offline contracts for entrez."""

from __future__ import annotations

import itertools
import json
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import mcp_server.entrez as entrez_rate_limit
import mcp_server.entrez as entrez_study4_recovery
import pytest
from Bio import Entrez
from mcp_server import entrez, pubmed_pilot_trace
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


# Short enough to keep the tests fast, long enough that thread scheduling
# noise cannot fake a passing spacing measurement.
_TEST_INTERVAL = 0.05


@pytest.fixture
def paced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pace at a test-sized interval, with the next slot already due."""
    monkeypatch.setattr(
        entrez_rate_limit, "_request_interval", lambda: _TEST_INTERVAL
    )
    monkeypatch.setattr(entrez_rate_limit, "_next_slot", 0.0)
    # Take the overdue slot here rather than in a test: a caller whose slot is
    # already in the past issues immediately, so the moment it records is the
    # moment the interpreter gets round to it, and that lag would show up as a
    # short first gap. Every slot a test then measures is one it waited for.
    entrez_rate_limit.entrez_call(lambda **_kwargs: None)


@pytest.mark.usefixtures("paced")
class TestEntrezRateLimit:
    def test_sequential_requests_are_spaced(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Back-to-back calls leave at least the interval between them.

        Driven by a fake clock rather than real elapsed time. Real time ties
        the assertion to OS scheduling: the gap it measures includes however
        long it takes the interpreter to get rescheduled after a real
        ``time.sleep`` returns, and machine load can stretch that enough to
        push a perfectly-spaced pair under the floor -- a false failure in the
        measurement, not in the pacer. A fake clock has no such lag, so this
        pins the pacer's slot arithmetic on its own.
        """
        fake_now = [0.0]

        def clock() -> float:
            return fake_now[0]

        def sleep(seconds: float) -> None:
            fake_now[0] += seconds

        monkeypatch.setattr(entrez_rate_limit, "_clock", clock)
        monkeypatch.setattr(entrez_rate_limit, "_sleep", sleep)
        monkeypatch.setattr(entrez_rate_limit, "_next_slot", 0.0)

        issued: list[float] = []

        def request(**_kwargs: Any) -> str:
            issued.append(clock())
            return "handle"

        for _ in range(3):
            assert entrez_rate_limit.entrez_call(request) == "handle"

        gaps = [b - a for a, b in itertools.pairwise(issued)]
        assert all(gap >= _TEST_INTERVAL for gap in gaps), gaps

    def test_concurrent_callers_do_not_burst(self) -> None:
        """Threads take separate slots instead of all firing at once.

        Biopython reads and writes its "previous request" timestamp
        without a lock, so every thread computes the same wait and then issues
        together -- the burst the limit exists to prevent, and the source of the
        429s that cost runs whole evidence sources.
        """
        issued: list[float] = []
        guard = threading.Lock()

        def request(**_kwargs: Any) -> None:
            with guard:
                issued.append(time.monotonic())

        threads = [
            threading.Thread(
                target=lambda: entrez_rate_limit.entrez_call(request)
            )
            for _ in range(6)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Measured as the span the six requests occupy rather than pair by pair:
        # a thread can be descheduled between waiting for its slot and recording
        # that it took it, which only ever pushes one timestamp later and so can
        # squeeze the pair after it. The span cannot be faked -- six requests
        # bursting together would occupy no time at all.
        assert len(issued) == 6
        span = max(issued) - min(issued)
        assert span >= 5 * _TEST_INTERVAL * 0.9, span

    def test_the_wait_does_not_hold_the_lock(self) -> None:
        """A slow request cannot block the next caller from taking its slot.

        The pacer bounds when requests *leave*; holding the lock across the call
        would also serialize their responses, turning a fan-out of independent
        fetches into one queue at the speed of the slowest.
        """
        started = threading.Event()
        release = threading.Event()

        def slow(**_kwargs: Any) -> None:
            started.set()
            release.wait(timeout=5)

        slow_thread = threading.Thread(
            target=lambda: entrez_rate_limit.entrez_call(slow)
        )
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

    def test_arguments_reach_the_underlying_call(self) -> None:
        """entrez_call forwards its keyword arguments verbatim."""
        seen: dict[str, Any] = {}

        def request(**kwargs: Any) -> str:
            seen.update(kwargs)
            return "handle"

        entrez_rate_limit.entrez_call(request, db="pubmed", id="42")

        assert seen == {"db": "pubmed", "id": "42"}


_STUDY_ID = "M12-04b4-study4-20260930"
_RECOVERY_FLAG = "COSCIENTIST_PUBMED_STUDY4_RECOVERY"
_STUDY_ID_ENV = "COSCIENTIST_PUBMED_STUDY_ID"


@pytest.fixture
def isolate_process_budget(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Each offline case starts with the one process budget unused."""
    max_tries = Entrez.max_tries
    sleep_between_tries = Entrez.sleep_between_tries
    monkeypatch.setattr(
        entrez_rate_limit, "_study4_bound_study_id", None, raising=False
    )
    monkeypatch.setattr(
        entrez_rate_limit, "_study4_retries_used", 0, raising=False
    )
    yield
    Entrez.max_tries = max_tries
    Entrez.sleep_between_tries = sleep_between_tries


def _trace(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", "study4-test-build")
    monkeypatch.setenv(_RECOVERY_FLAG, "1")
    monkeypatch.setenv(_STUDY_ID_ENV, _STUDY_ID)
    trace = pubmed_pilot_trace.new_pilot_trace("study4-test-run")
    assert trace is not None
    return trace


def _http_error(status: int, retry_after: str | None = None) -> HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError(
        "https://example.test/?api_key=must-not-appear&term=private",
        status,
        "synthetic response",
        headers,
        None,
    )


@pytest.mark.usefixtures("isolate_process_budget")
class TestEntrezStudy4Recovery:
    def test_recovery_is_default_off_even_when_legacy_trace_is_enabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
        monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", "legacy-build")
        monkeypatch.delenv(_RECOVERY_FLAG, raising=False)
        monkeypatch.delenv(_STUDY_ID_ENV, raising=False)
        trace = pubmed_pilot_trace.new_pilot_trace("legacy-run")
        assert trace is not None
        calls: list[dict[str, Any]] = []

        def failed(**kwargs: Any) -> None:
            calls.append(kwargs.copy())
            raise _http_error(429, "0")

        monkeypatch.setattr(Entrez, "esearch", failed)
        monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)

        with (
            entrez_rate_limit.pilot_trace_context(trace),
            pytest.raises(HTTPError),
        ):
            entrez_rate_limit.entrez_call(Entrez.esearch, db="pubmed", term="x")

        assert calls == [{"db": "pubmed", "term": "x"}]
        assert trace["entrez_calls"] == {"esearch": 1, "efetch": 0, "elink": 0}
        assert "entrez_recovery" not in trace
        assert "recovered_transient_attempts" not in trace

    def test_429_retry_reuses_exact_arguments_and_paces_both_attempts(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        trace = _trace(monkeypatch)
        calls: list[dict[str, Any]] = []
        sequence: list[str] = []

        def request(**kwargs: Any) -> str:
            calls.append(kwargs.copy())
            sequence.append("client-entry")
            if len(calls) == 1:
                raise _http_error(429, "0")
            return "retrieved"

        def pace() -> None:
            sequence.append("paced")

        monkeypatch.setattr(Entrez, "esearch", request)
        monkeypatch.setattr(entrez_rate_limit, "_await_slot", pace)
        monkeypatch.setattr(entrez_rate_limit, "_sleep", lambda _seconds: None)
        kwargs = {
            "db": "pubmed",
            "term": "private query",
            "api_key": None,
        }

        with entrez_rate_limit.pilot_trace_context(trace):
            result = entrez_rate_limit.entrez_call(Entrez.esearch, **kwargs)

        assert result == "retrieved"
        assert calls == [kwargs, kwargs]
        assert sequence == ["paced", "client-entry", "paced", "client-entry"]
        assert trace["entrez_calls"] == {"esearch": 1, "efetch": 0, "elink": 0}
        assert trace["entrez_recovery"] == {
            "study_id": _STUDY_ID,
            "policy": "study4-entrez-429-502-v1",
            "max_retries_per_logical_request": 1,
            "max_retries_per_study": 2,
            "retries_used": 1,
            "recovered_calls": 1,
            "exhausted_calls": 0,
            "client_entry_attempts": {"esearch": 2, "efetch": 0, "elink": 0},
            "process_retries_used_at_start": 0,
            "process_retries_used_at_end": 1,
        }
        event = trace["recovered_transient_attempts"][0]
        assert event == {
            "study_id": _STUDY_ID,
            "run_id": "study4-test-run",
            "server_build_id": "study4-test-build",
            "process_id": trace["process_id"],
            "operation": "esearch",
            "logical_request_ordinal": 1,
            "attempt_ordinal": 1,
            "http_status": 429,
            "retry_after_value": "0",
            "retry_after_raw_prefix": "0",
            "retry_after_raw_truncated": False,
            "wait_seconds": 0.0,
            "outcome": "recovered",
        }
        assert trace["entrez_recovery_call_outcomes"] == [
            {
                "study_id": _STUDY_ID,
                "run_id": "study4-test-run",
                "operation": "esearch",
                "logical_request_ordinal": 1,
                "retry_count": 1,
                "client_entry_attempts": 2,
                "final_outcome": "recovered",
            }
        ]
        trace_text = json.dumps(trace)
        assert "private query" not in trace_text
        assert "must-not-appear" not in trace_text
        assert "api_key" not in trace_text

    def test_recovery_configuration_rejects_missing_or_nonprotocol_identity(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
        monkeypatch.setenv(
            "COSCIENTIST_PUBMED_PILOT_BUILD_ID", "study4-test-build"
        )
        monkeypatch.setenv(_RECOVERY_FLAG, "1")
        monkeypatch.delenv(_STUDY_ID_ENV, raising=False)

        with pytest.raises(ValueError, match="study ID"):
            pubmed_pilot_trace.new_pilot_trace("missing-study-id")

        monkeypatch.setenv(_STUDY_ID_ENV, "M12-04b4e1a")
        with pytest.raises(ValueError, match="study ID"):
            pubmed_pilot_trace.new_pilot_trace(
                "implementation-id-is-not-study-id"
            )

        monkeypatch.setenv(_STUDY_ID_ENV, _STUDY_ID)
        monkeypatch.delenv("COSCIENTIST_PUBMED_PILOT_TRACE", raising=False)
        with pytest.raises(ValueError, match="requires pilot tracing"):
            pubmed_pilot_trace.new_pilot_trace("recovery-without-trace")

    def test_process_binding_cannot_change_study_or_reset_budget(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _trace(monkeypatch)
        assert entrez_rate_limit.reserve_study4_retry(_STUDY_ID) == 1
        assert entrez_rate_limit.bind_study4_recovery(_STUDY_ID) == 1
        with pytest.raises(ValueError, match="protocol study ID"):
            entrez_rate_limit.bind_study4_recovery("different-study")
        assert entrez_rate_limit.study4_retries_used(_STUDY_ID) == 1

    @pytest.mark.parametrize(
        ("retry_after", "expected"),
        [("²", 15.0), ("9" * 5000, None)],
    )
    def test_malformed_retry_after_boundaries_do_not_raise(
        self, retry_after: str, expected: float | None
    ) -> None:
        assert (
            entrez_study4_recovery.retry_after_delay(retry_after, lambda: 0)
            == expected
        )

    def test_one_logical_call_gets_at_most_one_retry_and_logs_terminal_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        trace = _trace(monkeypatch)
        calls = 0

        def failed(**_kwargs: Any) -> None:
            nonlocal calls
            calls += 1
            raise _http_error(502, "0")

        monkeypatch.setattr(Entrez, "esearch", failed)
        monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
        with (
            entrez_rate_limit.pilot_trace_context(trace),
            pytest.raises(HTTPError),
        ):
            entrez_rate_limit.entrez_call(Entrez.esearch, db="pubmed", term="x")

        assert calls == 2
        assert trace["entrez_recovery"]["retries_used"] == 1
        assert trace["entrez_recovery"]["exhausted_calls"] == 1
        assert [
            row["attempt_ordinal"]
            for row in trace["recovered_transient_attempts"]
        ] == [1, 2]
        assert {
            row["outcome"] for row in trace["recovered_transient_attempts"]
        } == {"exhausted"}
        assert trace["entrez_recovery_call_outcomes"] == [
            {
                "study_id": _STUDY_ID,
                "run_id": "study4-test-run",
                "operation": "esearch",
                "logical_request_ordinal": 1,
                "retry_count": 1,
                "client_entry_attempts": 2,
                "final_outcome": "exhausted",
            }
        ]

    @pytest.mark.parametrize("status", [400, 500, 503])
    def test_other_http_statuses_are_terminal_without_recovery_events(
        self, monkeypatch: pytest.MonkeyPatch, status: int
    ) -> None:
        trace = _trace(monkeypatch)
        calls = 0

        def failed(**_kwargs: Any) -> None:
            nonlocal calls
            calls += 1
            raise _http_error(status)

        monkeypatch.setattr(Entrez, "esearch", failed)
        monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
        with (
            entrez_rate_limit.pilot_trace_context(trace),
            pytest.raises(HTTPError),
        ):
            entrez_rate_limit.entrez_call(Entrez.esearch, db="pubmed", term="x")
        assert calls == 1
        assert trace["entrez_recovery"]["client_entry_attempts"]["esearch"] == 1
        assert trace["recovered_transient_attempts"] == []
        assert trace["entrez_recovery_call_outcomes"] == []

    def test_studywide_retry_budget_is_shared_across_trace_contexts(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        traces = [_trace(monkeypatch) for _ in range(3)]
        barrier = threading.Barrier(3)
        local = threading.local()
        monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
        monkeypatch.setattr(entrez_rate_limit, "_sleep", lambda _seconds: None)

        def request(**_kwargs: Any) -> str:
            attempts = getattr(local, "attempts", 0) + 1
            local.attempts = attempts
            if attempts == 1:
                barrier.wait(timeout=5)
                raise _http_error(429, "0")
            return "retrieved"

        monkeypatch.setattr(Entrez, "esearch", request)

        def run(trace: dict[str, Any]) -> str:
            with entrez_rate_limit.pilot_trace_context(trace):
                try:
                    return str(
                        entrez_rate_limit.entrez_call(
                            Entrez.esearch, db="pubmed", term="x"
                        )
                    )
                except HTTPError:
                    return "budget-exhausted"

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(run, traces))

        assert results.count("retrieved") == 2
        assert results.count("budget-exhausted") == 1
        assert (
            sum(trace["entrez_recovery"]["retries_used"] for trace in traces)
            == 2
        )
        assert (
            max(
                trace["entrez_recovery"]["process_retries_used_at_end"]
                for trace in traces
            )
            == 2
        )
        assert (
            sum(trace["entrez_recovery"]["recovered_calls"] for trace in traces)
            == 2
        )
        assert (
            sum(trace["entrez_recovery"]["exhausted_calls"] for trace in traces)
            == 1
        )
        assert (
            sum(len(trace["recovered_transient_attempts"]) for trace in traces)
            == 3
        )
        assert (
            sum(
                trace["entrez_recovery"]["client_entry_attempts"]["esearch"]
                for trace in traces
            )
            == 5
        )


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
