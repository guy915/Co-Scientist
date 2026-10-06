from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import mcp_server.entrez as entrez_rate_limit
import pytest
from Bio import Entrez
from mcp_server import pubmed_pilot_trace
from mcp_server.tests._entrez import (
    configure_trace,
    efetch_article,
    elink_without_pmc,
    esearch_ids,
    install_entrez,
    read_trace,
    search,
)
from mcp_server.tests._trace import _validate_study4_recovery_trace

_STUDY_ID = "M12-04b4-study4-20260930"
_RECOVERY_FLAG = "COSCIENTIST_PUBMED_STUDY4_RECOVERY"
_STUDY_ID_ENV = "COSCIENTIST_PUBMED_STUDY_ID"


@pytest.fixture
def isolate_process_budget(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Retry budgets are process-wide; each case needs a fresh allowance."""
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


@pytest.mark.usefixtures("isolate_process_budget")
class TestPubmedStudy4RecoveryTrace:
    @pytest.mark.parametrize(
        ("retry_after", "canonical_retry_after", "expected_wait"),
        [
            ("1 ", "1", 1.0),
            ("0" * 128 + "1", "1", 1.0),
            ("²", "!invalid", 15.0),
        ],
    )
    def test_maintained_pubmed_tool_retry_trace_passes_v4_validator_offline(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        retry_after: str,
        canonical_retry_after: str,
        expected_wait: float,
    ) -> None:
        run_id = "study4-producer-consumer"
        build_id = "study4-offline-build"
        cache_root = tmp_path / "cache"
        configure_trace(
            monkeypatch,
            cache_root,
            build_id,
            free_models=True,
            study_id=_STUDY_ID,
        )
        monkeypatch.setattr(entrez_rate_limit, "_sleep", lambda _seconds: None)
        search_calls: list[dict[str, Any]] = []

        def esearch(**kwargs: Any) -> Any:
            search_calls.append(kwargs)
            if len(search_calls) == 1:
                raise _http_error(429, retry_after)
            return esearch_ids("991")()

        install_entrez(
            monkeypatch,
            esearch=esearch,
            efetch=efetch_article,
            elink=elink_without_pmc,
        )

        result = search("offline producer consumer", run_id)
        trace = read_trace(cache_root, run_id, run_id)
        validated = _validate_study4_recovery_trace(
            trace,
            run_id=run_id,
            expected_build_id=build_id,
            serving_process={"pid": os.getpid()},
            study_retries_used_so_far=0,
        )

        assert list(result) == ["991"]
        assert (
            len(search_calls)
            == trace["entrez_recovery"]["client_entry_attempts"]["esearch"]
        )
        assert len(search_calls) == trace["entrez_calls"]["esearch"] + 1
        assert trace["incomplete_fetch_count"] == 0
        assert validated["entrez_recovery"] == trace["entrez_recovery"]
        assert validated["entrez_recovery"]["retries_used"] == 1
        assert (
            validated["recovered_transient_attempts"][0]["http_status"] == 429
        )
        event = validated["recovered_transient_attempts"][0]
        assert event["retry_after_value"] == canonical_retry_after
        assert event["retry_after_raw_prefix"] == retry_after[:128]
        assert event["retry_after_raw_truncated"] is (len(retry_after) > 128)
        assert event["wait_seconds"] == expected_wait

    def test_terminal_second_fetch_failure_preserves_incomplete_and_logical_counts(  # noqa: E501
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        run_id = "study4-terminal-fetch"
        cache_root = tmp_path / "cache"
        configure_trace(
            monkeypatch,
            cache_root,
            "study4-failure-build",
            free_models=True,
            study_id=_STUDY_ID,
        )
        monkeypatch.setattr(entrez_rate_limit, "_sleep", lambda _seconds: None)
        monkeypatch.setattr(Entrez, "esearch", esearch_ids("992"))
        fetch_calls = 0

        def failed_fetch(**_kwargs: Any) -> None:
            nonlocal fetch_calls
            fetch_calls += 1
            raise _http_error(429 if fetch_calls == 1 else 500, "0")

        install_entrez(monkeypatch, efetch=failed_fetch)

        result = search("terminal retry failure", run_id)
        trace = read_trace(cache_root, run_id, run_id)

        assert result == {}
        assert fetch_calls == 2
        assert trace["entrez_calls"]["efetch"] == 1
        assert trace["entrez_recovery"]["client_entry_attempts"]["efetch"] == 2
        assert trace["entrez_recovery"]["retries_used"] == 1
        assert trace["entrez_recovery"]["exhausted_calls"] == 1
        assert trace["entrez_recovery_call_outcomes"] == [
            {
                "study_id": _STUDY_ID,
                "run_id": run_id,
                "operation": "efetch",
                "logical_request_ordinal": 1,
                "retry_count": 1,
                "client_entry_attempts": 2,
                "final_outcome": "exhausted",
            }
        ]
        assert trace["incomplete_fetch_count"] == 1
        assert trace["fetch_errors"] == [
            {"stage": "metadata_fetch", "pmid": "992", "type": "HTTPError"}
        ]

    @pytest.mark.parametrize(
        ("status", "retry_after", "trace_value", "expected_wait"),
        [
            (429, "15", "15", 15.0),
            (502, None, None, 15.0),
            (429, "nonsense", "nonsense", 15.0),
        ],
    )
    def test_retry_after_seconds_and_missing_or_invalid_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        status: int,
        retry_after: str | None,
        trace_value: str | None,
        expected_wait: float,
    ) -> None:
        trace = _trace(monkeypatch)
        now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
        monkeypatch.setattr(
            entrez_rate_limit, "_wall_clock", lambda: now.timestamp()
        )
        waits: list[float] = []
        count = 0

        def request(**_kwargs: Any) -> str:
            nonlocal count
            count += 1
            if count == 1:
                raise _http_error(status, retry_after)
            return "retrieved"

        monkeypatch.setattr(Entrez, "efetch", request)
        monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
        monkeypatch.setattr(entrez_rate_limit, "_sleep", waits.append)
        with entrez_rate_limit.pilot_trace_context(trace):
            assert (
                entrez_rate_limit.entrez_call(
                    Entrez.efetch, db="pubmed", id="123"
                )
                == "retrieved"
            )

        assert waits == [expected_wait]
        assert (
            trace["recovered_transient_attempts"][0]["wait_seconds"]
            == expected_wait
        )
        assert (
            trace["recovered_transient_attempts"][0]["retry_after_value"]
            == trace_value
        )
        event = trace["recovered_transient_attempts"][0]
        assert event["retry_after_raw_prefix"] == (
            retry_after[:128] if retry_after is not None else None
        )
        assert event["retry_after_raw_truncated"] is (
            retry_after is not None and len(retry_after) > 128
        )

    def test_retry_after_http_date_is_honored_and_over_cap_is_terminal(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        trace = _trace(monkeypatch)
        now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
        monkeypatch.setattr(
            entrez_rate_limit, "_wall_clock", lambda: now.timestamp()
        )
        requested = format_datetime(now + timedelta(seconds=30), usegmt=True)
        waits: list[float] = []
        count = 0

        def request(**_kwargs: Any) -> str:
            nonlocal count
            count += 1
            if count == 1:
                raise _http_error(429, requested)
            return "retrieved"

        monkeypatch.setattr(Entrez, "elink", request)
        monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
        monkeypatch.setattr(entrez_rate_limit, "_sleep", waits.append)
        with entrez_rate_limit.pilot_trace_context(trace):
            assert (
                entrez_rate_limit.entrez_call(
                    Entrez.elink, dbfrom="pubmed", id="123"
                )
                == "retrieved"
            )
        assert waits == [30.0]

        trace = _trace(monkeypatch)
        count = 0

        def too_long(**_kwargs: Any) -> str:
            nonlocal count
            count += 1
            raise _http_error(429, "61")

        monkeypatch.setattr(Entrez, "elink", too_long)
        with (
            entrez_rate_limit.pilot_trace_context(trace),
            pytest.raises(HTTPError),
        ):
            entrez_rate_limit.entrez_call(
                Entrez.elink, dbfrom="pubmed", id="123"
            )
        assert count == 1
        assert trace["entrez_recovery"]["retries_used"] == 0
        assert trace["entrez_recovery"]["exhausted_calls"] == 1
        assert (
            trace["recovered_transient_attempts"][0]["outcome"]
            == "retry_after_over_cap"
        )
        assert (
            trace["entrez_recovery_call_outcomes"][0]["final_outcome"]
            == "retry_after_over_cap"
        )

        trace = _trace(monkeypatch)
        later = format_datetime(now + timedelta(seconds=61), usegmt=True)
        count = 0
        waits.clear()

        def date_too_long(**_kwargs: Any) -> str:
            nonlocal count
            count += 1
            raise _http_error(502, later)

        monkeypatch.setattr(Entrez, "elink", date_too_long)
        with (
            entrez_rate_limit.pilot_trace_context(trace),
            pytest.raises(HTTPError),
        ):
            entrez_rate_limit.entrez_call(
                Entrez.elink, dbfrom="pubmed", id="123"
            )
        assert count == 1
        assert waits == []
        assert (
            trace["recovered_transient_attempts"][0]["outcome"]
            == "retry_after_over_cap"
        )

    def test_retry_enters_the_existing_keyless_400ms_process_pacer(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        trace = _trace(monkeypatch)
        now: list[float] = [0.0]
        monkeypatch.setattr(
            entrez_rate_limit, "initialize_entrez", lambda: None
        )
        monkeypatch.setattr(entrez_rate_limit, "_clock", lambda: now[0])
        monkeypatch.setattr(
            entrez_rate_limit,
            "_sleep",
            lambda seconds: now.__setitem__(0, now[0] + seconds),
        )
        monkeypatch.setattr(entrez_rate_limit, "_next_slot", 0.0)
        issued_at: list[float] = []
        count = 0

        def request(**_kwargs: Any) -> str:
            nonlocal count
            count += 1
            issued_at.append(now[0])
            if count == 1:
                raise _http_error(429, "0")
            return "retrieved"

        monkeypatch.setattr(Entrez, "efetch", request)
        with entrez_rate_limit.pilot_trace_context(trace):
            assert entrez_rate_limit._request_interval() == 0.4
            assert (
                entrez_rate_limit.entrez_call(
                    Entrez.efetch, db="pubmed", id="123"
                )
                == "retrieved"
            )

        assert issued_at == [0.0, 0.4]
