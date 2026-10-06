"""Import helpers as mcp_server.tests to avoid mypy resolving one file under
two module names."""

import email.utils
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, NoReturn

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp_server.server import mcp
from starlette.applications import Starlette

_REAL_ASYNC_CLIENT = httpx.AsyncClient


class StubResponse:
    def __init__(self, payload: Any, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> Any:
        return self._payload

    @property
    def text(self) -> str:
        if isinstance(self._payload, str):
            return self._payload
        return str(self._payload)


class StubClient:
    def __init__(
        self,
        responses: list[Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._responses = list(responses) if responses else []
        self._error = error
        self.calls: list[tuple[str, Any]] = []

    async def __aenter__(self) -> "StubClient":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def get(
        self, url: str, **kwargs: Any
    ) -> StubResponse | httpx.Response:
        return self._serve(url, kwargs.get("params"))

    async def post(
        self, url: str, json: Any = None, **_: Any
    ) -> StubResponse | httpx.Response:
        return self._serve(url, json)

    def _serve(self, url: str, payload: Any) -> StubResponse | httpx.Response:
        # Pagination mutates its parameter dict between calls.
        self.calls.append(
            (url, dict(payload) if isinstance(payload, dict) else payload)
        )
        if self._error is not None:
            raise self._error
        if not self._responses:
            raise AssertionError(f"stub has no response queued for {url}")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, (StubResponse, httpx.Response)):
            return response
        return StubResponse(response)


def _install(monkeypatch: pytest.MonkeyPatch, client: StubClient) -> StubClient:
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)
    return client


def stub_responses(
    monkeypatch: pytest.MonkeyPatch, *payloads: Any
) -> StubClient:
    return _install(monkeypatch, StubClient(responses=list(payloads)))


def stub_failure(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> StubClient:
    return _install(monkeypatch, StubClient(error=error))


def stub_unreachable(
    monkeypatch: pytest.MonkeyPatch,
    message: str = "must not reach the network",
) -> StubClient:
    """A leaked request must raise rather than silently satisfy a branch that
    should reject before I/O."""
    return stub_failure(monkeypatch, RuntimeError(message))


def asgi_client_factory(app: Any) -> Callable[..., httpx.AsyncClient]:
    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("follow_redirects", None)
        return _REAL_ASYNC_CLIENT(
            **kwargs,
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )

    return factory


@asynccontextmanager
async def registered_tools() -> AsyncIterator[Any]:
    """A FastMCP client connected to the real registered server in-process."""
    mcp_app = mcp.http_app()
    app = Starlette(lifespan=mcp_app.lifespan)
    app.mount("/", mcp_app)
    transport = StreamableHttpTransport(
        "http://test/mcp", httpx_client_factory=asgi_client_factory(app)
    )
    async with app.router.lifespan_context(app), Client(transport) as client:
        yield client


def transport_responses(
    monkeypatch: pytest.MonkeyPatch, *responses: Any
) -> list[httpx.Request]:
    queued = list(responses)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        response = queued.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, httpx.Response):
            return response
        return httpx.Response(200, json=response)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: _REAL_ASYNC_CLIENT(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    return requests


MAX_TRACE_IDS = 9


def _trace_evidence(
    path: Path, run_id: str, expected_build: str
) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("Maintained PubMed trace is missing")
    trace = json.loads(path.read_text(encoding="utf-8"))
    if (
        trace.get("run_id") != run_id
        or trace.get("server_build_id") != expected_build
    ):
        raise ValueError(
            "Maintained PubMed trace does not match this request/build"
        )
    attempts = trace.get("attempts", [])
    fetched = trace.get("fetched", [])
    if len(attempts) > 8 or len(fetched) > MAX_TRACE_IDS:
        raise ValueError("Maintained PubMed trace exceeds its frozen bound")
    return {
        "run_id": run_id,
        "server_build_id": expected_build,
        "sort": trace.get("sort"),
        "attempts": [
            {
                "rung_index": item.get("rung_index"),
                "rung_type": item.get("rung_type"),
                "count": item.get("count"),
                "first_ids": list(item.get("first_ids", []))[:MAX_TRACE_IDS],
                "sort": item.get("sort"),
            }
            for item in attempts
        ],
        "selected": {
            key: trace.get("selected", {}).get(key)
            for key in ("rung_index", "rung_type", "count", "ids", "sort")
        }
        if isinstance(trace.get("selected"), dict)
        else None,
        "pre_search_shared_pool": {
            "file_count": trace.get("pre_search_shared_pool", {}).get(
                "file_count"
            ),
            "metadata_count": trace.get("pre_search_shared_pool", {}).get(
                "metadata_count"
            ),
            "first_ids": trace.get("pre_search_shared_pool", {}).get(
                "first_ids", []
            )[:MAX_TRACE_IDS],
        },
        "fetched": [
            {
                "pmid": item.get("pmid"),
                "fetched": item.get("fetched"),
                "pmc_available": item.get("pmc_available"),
                "abstract_available": item.get("abstract_available"),
            }
            for item in fetched
        ],
        "final_ids": list(trace.get("final_ids", []))[:3],
        "shared_pool_supplements": [
            {
                key: item.get(key)
                for key in (
                    "pmid",
                    "source",
                    "origin",
                    "preexisting",
                    "matched_esearch_first_ids",
                )
            }
            for item in trace.get("shared_pool_supplements", [])[:3]
        ],
    }


STUDY4_IDENTITY = "M12-04b4-study4-20260930"

STUDY4_RECOVERY_POLICY = "study4-entrez-429-502-v1"

STUDY4_MAX_RETRIES_PER_LOGICAL_REQUEST = 1

STUDY4_MAX_RETRIES_PER_STUDY = 2

STUDY4_RETRYABLE_HTTP_STATUSES = (429, 502)

STUDY4_RETRY_AFTER_MAX_SECONDS = 60

STUDY4_RETRY_AFTER_DEFAULT_SECONDS = 15

STUDY4_MAX_TRACE_RECOVERY_ROWS = 256

_STUDY4_OPERATION_ORDER = ("esearch", "efetch", "elink")

_STUDY4_OPERATIONS = frozenset(_STUDY4_OPERATION_ORDER)

_STUDY4_RECOVERY_OUTCOMES = frozenset(
    {"recovered", "exhausted", "study_budget_exhausted", "retry_after_over_cap"}
)


def _validate_study4_recovery_trace(  # noqa: C901
    trace: dict[str, Any],
    *,
    run_id: str,
    expected_build_id: str,
    serving_process: dict[str, Any],
    study_retries_used_so_far: int,
) -> dict[str, Any]:

    def reject() -> NoReturn:
        raise ValueError(
            "Study 4 Entrez recovery trace is incomplete or inconsistent"
        )

    def parse_retry_after(value: str) -> tuple[str, float | None]:
        value = value.strip()
        if value.isascii() and value.isdecimal():
            try:
                seconds = int(value)
            except ValueError:
                return "invalid", None
            return "seconds", float(seconds)
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return "invalid", None
        return ("date", None) if parsed is not None else ("invalid", None)

    recovery = trace.get("entrez_recovery")
    if (
        trace.get("run_id") != run_id
        or trace.get("server_build_id") != expected_build_id
        or trace.get("process_id") != serving_process.get("pid")
        or not isinstance(recovery, dict)
        or recovery.get("study_id") != STUDY4_IDENTITY
        or recovery.get("policy") != STUDY4_RECOVERY_POLICY
        or recovery.get("max_retries_per_logical_request")
        != STUDY4_MAX_RETRIES_PER_LOGICAL_REQUEST
        or recovery.get("max_retries_per_study") != STUDY4_MAX_RETRIES_PER_STUDY
    ):
        reject()

    calls = trace.get("entrez_calls")
    client_attempts = recovery.get("client_entry_attempts")
    if (
        not isinstance(calls, dict)
        or set(calls) != _STUDY4_OPERATIONS
        or any(type(count) is not int or count < 0 for count in calls.values())
        or not isinstance(client_attempts, dict)
        or set(client_attempts) != _STUDY4_OPERATIONS
        or any(
            type(count) is not int or count < 0
            for count in client_attempts.values()
        )
    ):
        reject()

    counters: dict[str, Any] = {
        name: recovery.get(name)
        for name in ("retries_used", "recovered_calls", "exhausted_calls")
    }
    if any(type(value) is not int or value < 0 for value in counters.values()):
        reject()
    process_start = recovery.get("process_retries_used_at_start")
    process_end = recovery.get("process_retries_used_at_end")
    if (
        type(study_retries_used_so_far) is not int
        or not 0 <= study_retries_used_so_far <= STUDY4_MAX_RETRIES_PER_STUDY
        or type(process_start) is not int
        or type(process_end) is not int
        or not 0 <= process_start <= process_end
        or process_end > STUDY4_MAX_RETRIES_PER_STUDY
        or counters["retries_used"] > process_end - process_start
        or study_retries_used_so_far + counters["retries_used"]
        > STUDY4_MAX_RETRIES_PER_STUDY
    ):
        reject()

    attempts = trace.get("recovered_transient_attempts")
    outcomes = trace.get("entrez_recovery_call_outcomes")
    total_logical_calls = sum(calls.values())
    if (
        not isinstance(attempts, list)
        or len(attempts)
        > min(
            STUDY4_MAX_TRACE_RECOVERY_ROWS,
            total_logical_calls * (STUDY4_MAX_RETRIES_PER_LOGICAL_REQUEST + 1),
        )
        or not isinstance(outcomes, list)
        or len(outcomes)
        > min(STUDY4_MAX_TRACE_RECOVERY_ROWS, total_logical_calls)
    ):
        reject()

    outcome_by_request: dict[tuple[str, int], dict[str, Any]] = {}
    recovered_calls = 0
    exhausted_calls = 0
    retries_used = 0
    for row in outcomes:
        if not isinstance(row, dict):
            reject()
        operation = row.get("operation")
        ordinal = row.get("logical_request_ordinal")
        if (
            not isinstance(operation, str)
            or operation not in _STUDY4_OPERATIONS
            or type(ordinal) is not int
        ):
            reject()
        retry_count = row.get("retry_count")
        entry_count = row.get("client_entry_attempts")
        final_outcome = row.get("final_outcome")
        key = (operation, ordinal)
        if (
            row.get("study_id") != STUDY4_IDENTITY
            or row.get("run_id") != run_id
            or not 1 <= ordinal <= calls[operation]
            or key in outcome_by_request
            or type(retry_count) is not int
            or retry_count not in {0, STUDY4_MAX_RETRIES_PER_LOGICAL_REQUEST}
            or type(entry_count) is not int
            or entry_count != 1 + retry_count
            or not isinstance(final_outcome, str)
            or final_outcome not in _STUDY4_RECOVERY_OUTCOMES
        ):
            reject()
        if final_outcome in {"recovered", "exhausted"} and retry_count != 1:
            reject()
        if final_outcome == "recovered":
            recovered_calls += 1
        else:
            exhausted_calls += 1
        retries_used += retry_count
        outcome_by_request[key] = row

    if (
        counters["retries_used"] != retries_used
        or counters["recovered_calls"] != recovered_calls
        or counters["exhausted_calls"] != exhausted_calls
        or recovered_calls + exhausted_calls != len(outcomes)
    ):
        reject()

    attempts_by_request: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in attempts:
        if not isinstance(row, dict):
            reject()
        operation = row.get("operation")
        ordinal = row.get("logical_request_ordinal")
        attempt_ordinal = row.get("attempt_ordinal")
        status = row.get("http_status")
        wait_seconds: Any = row.get("wait_seconds")
        retry_after = row.get("retry_after_value")
        retry_after_raw_prefix = row.get("retry_after_raw_prefix")
        retry_after_raw_truncated = row.get("retry_after_raw_truncated")
        if (
            not isinstance(operation, str)
            or operation not in _STUDY4_OPERATIONS
            or type(ordinal) is not int
        ):
            reject()
        key = (operation, ordinal)
        if (
            row.get("study_id") != STUDY4_IDENTITY
            or row.get("run_id") != run_id
            or row.get("server_build_id") != expected_build_id
            or row.get("process_id") != serving_process.get("pid")
            or not 1 <= ordinal <= calls[operation]
            or type(attempt_ordinal) is not int
            or attempt_ordinal not in {1, 2}
            or type(status) is not int
            or status not in STUDY4_RETRYABLE_HTTP_STATUSES
            or isinstance(wait_seconds, bool)
            or not isinstance(wait_seconds, (int, float))
            or not 0 <= wait_seconds <= STUDY4_RETRY_AFTER_MAX_SECONDS
            or (
                retry_after is not None
                and (
                    not isinstance(retry_after, str)
                    or len(retry_after) > 128
                    or any(
                        ord(char) != 9 and not 32 <= ord(char) <= 126
                        for char in retry_after
                    )
                )
            )
            or type(retry_after_raw_truncated) is not bool
            or (
                retry_after_raw_prefix is not None
                and (
                    not isinstance(retry_after_raw_prefix, str)
                    or len(retry_after_raw_prefix) > 128
                )
            )
            or (retry_after is None) != (retry_after_raw_prefix is None)
        ):
            reject()
        attempts_by_request.setdefault(key, []).append(row)

    for operation in _STUDY4_OPERATION_ORDER:
        expected_entries = calls[operation] + sum(
            row["retry_count"]
            for (row_operation, _), row in outcome_by_request.items()
            if row_operation == operation
        )
        if client_attempts[operation] != expected_entries:
            reject()

    for key, row in outcome_by_request.items():
        request_attempts = attempts_by_request.pop(key, [])
        ordinals = [
            attempt.get("attempt_ordinal") for attempt in request_attempts
        ]
        final_outcome = row["final_outcome"]
        if (
            not request_attempts
            or ordinals != list(range(1, len(ordinals) + 1))
            or len(ordinals) > row["client_entry_attempts"]
            or row["client_entry_attempts"] != 1 + row["retry_count"]
            or any(
                attempt.get("outcome") != final_outcome
                for attempt in request_attempts
            )
        ):
            reject()
        if final_outcome == "recovered" and ordinals != [1]:
            reject()
        retry_count = row["retry_count"]
        for index, attempt in enumerate(request_attempts):
            retry_was_issued = index < retry_count
            retry_after = attempt.get("retry_after_value")
            wait_seconds = attempt.get("wait_seconds")
            if not retry_was_issued:
                if wait_seconds != 0:
                    reject()
                continue
            if retry_after is None:
                if wait_seconds != STUDY4_RETRY_AFTER_DEFAULT_SECONDS:
                    reject()
                continue
            retry_after_kind, requested_wait = parse_retry_after(retry_after)
            if retry_after_kind == "seconds":
                if (
                    requested_wait is None
                    or requested_wait > STUDY4_RETRY_AFTER_MAX_SECONDS
                ):
                    reject()
                if wait_seconds != requested_wait:
                    reject()
            elif retry_after_kind == "date":
                if wait_seconds > STUDY4_RETRY_AFTER_MAX_SECONDS:
                    reject()
            elif wait_seconds != STUDY4_RETRY_AFTER_DEFAULT_SECONDS:
                reject()
        final_attempt = request_attempts[-1]
        final_retry_after = final_attempt.get("retry_after_value")
        final_kind, final_delay = (
            parse_retry_after(final_retry_after)
            if isinstance(final_retry_after, str)
            else ("missing", None)
        )
        if final_kind == "seconds":
            if (
                final_delay is not None
                and final_delay > STUDY4_RETRY_AFTER_MAX_SECONDS
            ):
                if final_outcome != "retry_after_over_cap":
                    reject()
            elif final_outcome == "retry_after_over_cap":
                reject()
        if final_kind == "invalid" and final_outcome == "retry_after_over_cap":
            reject()

    if attempts_by_request:
        reject()
    if any(row["final_outcome"] != "recovered" for row in outcomes):
        reject()
    return {
        "entrez_recovery": recovery,
        "recovered_transient_attempts": attempts,
        "entrez_recovery_call_outcomes": outcomes,
    }
