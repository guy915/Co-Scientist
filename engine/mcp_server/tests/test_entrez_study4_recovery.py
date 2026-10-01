"""Offline tests for the default-off prospective Study 4 Entrez recovery."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from typing import Any
from urllib.error import HTTPError

import pytest
from Bio import Entrez
from mcp_server import (
    entrez_rate_limit,
    entrez_study4_recovery,
    pubmed_pilot_trace,
)

_STUDY_ID = "M12-04b4-study4-20260930"
_RECOVERY_FLAG = "COSCIENTIST_PUBMED_STUDY4_RECOVERY"
_STUDY_ID_ENV = "COSCIENTIST_PUBMED_STUDY_ID"


@pytest.fixture(autouse=True)
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


def test_recovery_is_default_off_even_when_legacy_trace_is_enabled(
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

    with entrez_rate_limit.pilot_trace_context(trace), pytest.raises(HTTPError):
        entrez_rate_limit.entrez_call(Entrez.esearch, db="pubmed", term="x")

    assert calls == [{"db": "pubmed", "term": "x"}]
    assert trace["entrez_calls"] == {"esearch": 1, "efetch": 0, "elink": 0}
    assert "entrez_recovery" not in trace
    assert "recovered_transient_attempts" not in trace


def test_429_retry_reuses_exact_arguments_and_paces_both_attempts(
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", "study4-test-build")
    monkeypatch.setenv(_RECOVERY_FLAG, "1")
    monkeypatch.delenv(_STUDY_ID_ENV, raising=False)

    with pytest.raises(ValueError, match="study ID"):
        pubmed_pilot_trace.new_pilot_trace("missing-study-id")

    monkeypatch.setenv(_STUDY_ID_ENV, "M12-04b4e1a")
    with pytest.raises(ValueError, match="study ID"):
        pubmed_pilot_trace.new_pilot_trace("implementation-id-is-not-study-id")

    monkeypatch.setenv(_STUDY_ID_ENV, _STUDY_ID)
    monkeypatch.delenv("COSCIENTIST_PUBMED_PILOT_TRACE", raising=False)
    with pytest.raises(ValueError, match="requires pilot tracing"):
        pubmed_pilot_trace.new_pilot_trace("recovery-without-trace")


def test_process_binding_cannot_change_study_or_reset_budget(
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
    retry_after: str, expected: float | None
) -> None:
    assert (
        entrez_study4_recovery.retry_after_delay(retry_after, lambda: 0)
        == expected
    )


def test_one_logical_call_gets_at_most_one_retry_and_logs_terminal_failure(
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
    with entrez_rate_limit.pilot_trace_context(trace), pytest.raises(HTTPError):
        entrez_rate_limit.entrez_call(Entrez.esearch, db="pubmed", term="x")

    assert calls == 2
    assert trace["entrez_recovery"]["retries_used"] == 1
    assert trace["entrez_recovery"]["exhausted_calls"] == 1
    assert [
        row["attempt_ordinal"] for row in trace["recovered_transient_attempts"]
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
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    trace = _trace(monkeypatch)
    calls = 0

    def failed(**_kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        raise _http_error(status)

    monkeypatch.setattr(Entrez, "esearch", failed)
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
    with entrez_rate_limit.pilot_trace_context(trace), pytest.raises(HTTPError):
        entrez_rate_limit.entrez_call(Entrez.esearch, db="pubmed", term="x")
    assert calls == 1
    assert trace["entrez_recovery"]["client_entry_attempts"]["esearch"] == 1
    assert trace["recovered_transient_attempts"] == []
    assert trace["entrez_recovery_call_outcomes"] == []


def test_studywide_retry_budget_is_shared_across_trace_contexts(
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
        sum(trace["entrez_recovery"]["retries_used"] for trace in traces) == 2
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
        sum(len(trace["recovered_transient_attempts"]) for trace in traces) == 3
    )
    assert (
        sum(
            trace["entrez_recovery"]["client_entry_attempts"]["esearch"]
            for trace in traces
        )
        == 5
    )
