from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import mcp_server.entrez as entrez_rate_limit
import pytest
from Bio import Entrez
from mcp_server.tests._entrez import CannedEntrezHandle as _CannedEntrezHandle
from mcp_server.tests._entrez import configure_trace, install_entrez
from mcp_server.tests._entrez import pubmed_article as _pubmed_article
from mcp_server.tests._httpx import _validate_study4_recovery_trace
from mcp_server.tests.test_entrez import (
    _STUDY_ID,
    _http_error,
    _trace,
    isolate_process_budget,
)
from mcp_server.tools.lit_review import search_pubmed as pubmed_tool

__all__ = ["isolate_process_budget"]


def _study4_trace_validator() -> Any:
    return _validate_study4_recovery_trace


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

        def esearch(**kwargs: Any) -> _CannedEntrezHandle:
            search_calls.append(kwargs)
            if len(search_calls) == 1:
                raise _http_error(429, retry_after)
            return _CannedEntrezHandle({"IdList": ["991"]})

        install_entrez(
            monkeypatch,
            esearch=esearch,
            efetch=lambda **kwargs: _CannedEntrezHandle(
                _pubmed_article(str(kwargs["id"]))
            ),
            elink=lambda **_kwargs: _CannedEntrezHandle([{"LinkSetDb": []}]),
        )

        result = asyncio.run(
            pubmed_tool.pubmed_search_with_fulltext(
                query="offline producer consumer",
                slug=run_id,
                max_papers=1,
                run_id=run_id,
            )
        )
        trace_path = (
            cache_root
            / "pubmed"
            / run_id
            / "runs"
            / run_id
            / ".search-trace.json"
        )
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        validated = _study4_trace_validator()(
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
        monkeypatch.setattr(
            Entrez,
            "esearch",
            lambda **_kwargs: _CannedEntrezHandle({"IdList": ["992"]}),
        )
        fetch_calls = 0

        def failed_fetch(**_kwargs: Any) -> None:
            nonlocal fetch_calls
            fetch_calls += 1
            raise _http_error(429 if fetch_calls == 1 else 500, "0")

        install_entrez(monkeypatch, efetch=failed_fetch)

        result = asyncio.run(
            pubmed_tool.pubmed_search_with_fulltext(
                query="terminal retry failure",
                slug=run_id,
                max_papers=1,
                run_id=run_id,
            )
        )
        trace_path = (
            cache_root
            / "pubmed"
            / run_id
            / "runs"
            / run_id
            / ".search-trace.json"
        )
        trace = json.loads(trace_path.read_text(encoding="utf-8"))

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
            (429, "15 ", "15", 15.0),
            (429, "0" * 128 + "1", "1", 1.0),
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
