"""Shared httpx stand-ins for the tools that call a remote HTTP API.

Every tool in this package reaches its upstream through a fresh
``httpx.AsyncClient`` context manager, so the whole suite fakes the same
seam: patch ``httpx.AsyncClient`` with something that answers ``post``
(the INDRA CoGex endpoints) or ``get`` (the ChEMBL/UniProt lookups) from
canned data instead of opening a socket. Those stand-ins live here, in
one place, because six tool-family modules each carrying their own copy
is exactly how three mutually incompatible client shapes grew from one
original.

The convention is ``engine/tests``': an underscore-prefixed helper module
exporting names without the underscore. Only the import path differs, and
not by choice -- ``mcp_server`` is itself a package, so this directory's
dotted name is ``mcp_server.tests`` even without an ``__init__.py``, and
that is the name both pytest and mypy resolve. Importing it any shorter
way gives mypy two names for one file, which it rejects outright.
"""

import email.utils
import json
from pathlib import Path
from typing import Any, NoReturn, cast

import httpx
import pytest


class StubResponse:
    """A canned httpx.Response standing in for a real upstream reply."""

    def __init__(self, payload: Any) -> None:
        """Store the payload ``json``/``text`` hands back."""
        self._payload = payload

    def raise_for_status(self) -> None:
        """Represent a 2xx response: never raises."""

    def json(self) -> Any:
        """Return the fixture payload."""
        return self._payload

    @property
    def text(self) -> str:
        """Return the fixture payload as text, for an XML/Atom source."""
        if isinstance(self._payload, str):
            return self._payload
        return str(self._payload)


class StubClient:
    """A canned httpx.AsyncClient serving queued payloads, or raising.

    Payloads are served in call order, which is what a tool issuing more
    than one request needs (the gene-disease network follows its genes
    call with a variants call); a single-request tool simply queues one.
    Every request is recorded as ``(url, payload)`` -- the JSON body for a
    POST, the query params for a GET -- so tests can assert on the
    request the tool built as well as on what it did with the answer.
    """

    def __init__(
        self,
        responses: list[Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Queue the payloads to serve, or the error to raise instead.

        Args:
            responses: Payloads returned in call order, one per request.
            error: Exception raised by every request instead of answering.
        """
        self._responses = list(responses) if responses else []
        self._error = error
        self.calls: list[tuple[str, Any]] = []

    async def __aenter__(self) -> "StubClient":
        """Enter the async context manager every tool opens."""
        return self

    async def __aexit__(self, *_: Any) -> bool:
        """Leave the context manager without suppressing exceptions."""
        return False

    async def get(self, url: str, **kwargs: Any) -> StubResponse:
        """Record the GET and serve the next queued payload."""
        return self._serve(url, kwargs.get("params"))

    async def post(self, url: str, json: Any = None, **_: Any) -> StubResponse:
        """Record the POST and serve the next queued payload.

        Keyword arguments beyond the body are accepted and ignored, the
        same way ``get`` ignores everything but ``params``: a caller that
        sends auth headers (Tavily) must not need a second stub.
        """
        return self._serve(url, json)

    def _serve(self, url: str, payload: Any) -> StubResponse:
        """Record one request, then raise the error or pop a response."""
        self.calls.append((url, payload))
        if self._error is not None:
            raise self._error
        if not self._responses:
            raise AssertionError(f"stub has no response queued for {url}")
        return StubResponse(self._responses.pop(0))


def _install(monkeypatch: pytest.MonkeyPatch, client: StubClient) -> StubClient:
    """Patch ``httpx.AsyncClient`` to hand out ``client``, and return it."""
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)
    return client


def stub_responses(
    monkeypatch: pytest.MonkeyPatch, *payloads: Any
) -> StubClient:
    """Patch httpx.AsyncClient to serve ``payloads`` in call order.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        *payloads: One payload per request the tool under test makes.

    Returns:
        The installed client, whose ``calls`` record those requests.
    """
    return _install(monkeypatch, StubClient(responses=list(payloads)))


def stub_failure(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> StubClient:
    """Patch httpx.AsyncClient to raise ``error`` instead of responding.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        error: The transport failure every request raises.

    Returns:
        The installed client, whose ``calls`` record those requests.
    """
    return _install(monkeypatch, StubClient(error=error))


def stub_unreachable(
    monkeypatch: pytest.MonkeyPatch,
    message: str = "must not reach the network",
) -> StubClient:
    """Patch httpx.AsyncClient so any request at all fails the test.

    For the branches a tool must reject before issuing a request. The
    RuntimeError is never asserted on; it exists so a leaked request
    surfaces as this message instead of as a quietly passing test.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        message: The RuntimeError text a leaked request would carry.

    Returns:
        The installed client, whose ``calls`` stay empty when the tool
        short-circuits as intended.
    """
    return stub_failure(monkeypatch, RuntimeError(message))


# Maintained trace contracts from the archived Sakana reference campaign.
_ROOT = Path(__file__).resolve().parents[3]
_PUBMED_CLIENT = str((_ROOT / "engine/mcp_server/pubmed_client.py").resolve())
_BATCH_SIZE = 9
# The frozen novelty envelope sets MAX_PAPERS to three. Keep this sibling
# stdlib-only so its producer proof can run in the dedicated MCP venv.
_MAX_FINAL_IDS = 3
_RETRY_POLICY = {"max_tries": 1, "sleep_between_tries": 0}
_BATCH_FIELDS = {
    "batch_index",
    "input_pmids",
    "cache_hit_pmids",
    "efetch_pmids",
    "efetch_returned_pmids",
    "elink_pmids",
    "elink_results",
}


def _reject() -> NoReturn:
    raise ValueError(
        "PubMed batch trace attestation is incomplete or inconsistent"
    )


def _is_pmid(value: Any) -> bool:
    return isinstance(value, str) and value.isascii() and value.isdecimal()


def _validate_identity(
    trace: dict[str, Any],
    *,
    run_id: str,
    expected_build_id: str,
    serving_process: dict[str, Any],
) -> None:
    if (
        trace.get("run_id") != run_id
        or trace.get("server_build_id") != expected_build_id
        or type(trace.get("process_id")) is not int
        or trace.get("process_id") != serving_process.get("pid")
        or trace.get("source_file") != _PUBMED_CLIENT
        or trace.get("sort") != "pub_date"
        or "error" not in trace
        or trace["error"] is not None
        or trace.get("outcome") not in {"nonempty", "empty"}
        or (
            "mcp_tree" in serving_process
            and serving_process["mcp_tree"] != expected_build_id
        )
    ):
        _reject()
    if trace.get("entrez_retry_policy") != _RETRY_POLICY:
        _reject()


def _validated_calls(trace: dict[str, Any]) -> dict[str, int]:
    calls = trace.get("entrez_calls")
    if not isinstance(calls, dict) or set(calls) != {
        "esearch",
        "efetch",
        "elink",
    }:
        _reject()
    if any(type(value) is not int or value < 0 for value in calls.values()):
        _reject()
    return calls


def _search_selection(  # noqa: C901
    trace: dict[str, Any], calls: dict[str, int]
) -> list[str]:
    attempts = trace.get("attempts")
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= 3:
        _reject()
    for attempt in attempts:
        if not isinstance(attempt, dict):
            _reject()
        ids = attempt.get("first_ids")
        if (
            attempt.get("operation") != "esearch"
            or attempt.get("sort") != "pub_date"
            or "error_type" in attempt
            or type(attempt.get("count")) is not int
            or not isinstance(ids, list)
            or attempt["count"] != len(ids)
        ):
            _reject()
    if calls["esearch"] != len(attempts):
        _reject()

    selected = trace.get("selected")
    if selected is None:
        selected_ids: list[str] = []
        if any(attempt["count"] for attempt in attempts):
            _reject()
        return selected_ids
    if not isinstance(selected, dict):
        _reject()
    selected_ids_raw = selected.get("ids")
    if (
        not isinstance(selected_ids_raw, list)
        or not selected_ids_raw
        or len(selected_ids_raw) > _BATCH_SIZE
        or any(not _is_pmid(pmid) for pmid in selected_ids_raw)
        or len(set(selected_ids_raw)) != len(selected_ids_raw)
        or selected.get("sort") != "pub_date"
        or type(selected.get("count")) is not int
        or selected["count"] != len(selected_ids_raw)
    ):
        _reject()
    selected_ids = cast(list[str], selected_ids_raw)
    matches = [
        attempt
        for attempt in attempts
        if attempt.get("rung_index") == selected.get("rung_index")
        and attempt.get("rung_type") == selected.get("rung_type")
    ]
    if len(matches) != 1 or matches[0]["first_ids"] != selected_ids:
        _reject()
    return selected_ids


def _validate_empty_trace(trace: dict[str, Any], calls: dict[str, int]) -> None:
    if (
        "metadata_batching" in trace
        or calls["efetch"] != 0
        or calls["elink"] != 0
    ):
        _reject()


def _validate_pool_and_errors(trace: dict[str, Any]) -> None:
    pool = trace.get("pre_search_shared_pool")
    if (
        not isinstance(pool, dict)
        or type(pool.get("file_count")) is not int
        or type(pool.get("metadata_count")) is not int
        or pool["file_count"] != 0
        or pool["metadata_count"] != 0
        or pool.get("first_ids") != []
        or trace.get("shared_pool_supplements") != []
        or trace.get("fetch_errors") != []
        or type(trace.get("incomplete_fetch_count")) is not int
        or trace["incomplete_fetch_count"] != 0
    ):
        _reject()


def _fetched_pmc_availability(
    trace: dict[str, Any], selected_ids: list[str]
) -> dict[str, bool]:
    fetched = trace.get("fetched")
    origins = trace.get("metadata_origins")
    if (
        not isinstance(fetched, list)
        or len(fetched) != len(selected_ids)
        or not isinstance(origins, dict)
        or set(origins) != set(selected_ids)
        or [row.get("pmid") for row in fetched if isinstance(row, dict)]
        != selected_ids
    ):
        _reject()
    pmc_available: dict[str, bool] = {}
    for row in fetched:
        if not isinstance(row, dict):
            _reject()
        paper_id = row.get("pmid")
        if (
            not isinstance(paper_id, str)
            or not _is_pmid(paper_id)
            or row.get("fetched") is not True
            or row.get("incomplete") is not False
            or row.get("metadata_origin") != "entrez_fetch"
            or origins.get(paper_id) != "entrez_fetch"
            or type(row.get("pmc_available")) is not bool
        ):
            _reject()
        pmc_available[paper_id] = row["pmc_available"]
    return pmc_available


def _validate_final_ids(
    trace: dict[str, Any],
    *,
    selected_ids: list[str],
    returned_ids: list[str] | None,
) -> None:
    final_ids = trace.get("final_ids")
    expected = returned_ids if returned_ids is not None else []
    if (
        not isinstance(final_ids, list)
        or len(final_ids) > _MAX_FINAL_IDS
        or any(not _is_pmid(pmid) for pmid in final_ids)
        or len(set(final_ids)) != len(final_ids)
        or final_ids != expected
        or not set(final_ids).issubset(selected_ids)
        or (trace["outcome"] == "nonempty") != bool(final_ids)
    ):
        _reject()


def _validate_recovery_fields(
    trace: dict[str, Any], serving_process: dict[str, Any]
) -> None:
    recovery_fields = {
        "entrez_recovery",
        "recovered_transient_attempts",
        "entrez_recovery_call_outcomes",
    }
    if (
        recovery_fields.intersection(trace)
        or "study4_recovery" in serving_process
    ):
        _reject()


def _validate_link_result(  # noqa: C901
    result: Any, paper_id: str, pmc_available: dict[str, bool]
) -> None:
    if (
        not isinstance(result, dict)
        or set(result) != {"pmid", "status", "pmc_id"}
        or result.get("pmid") != paper_id
    ):
        _reject()
    status, pmc_id = result.get("status"), result.get("pmc_id")
    if status == "linked":
        if not _is_pmid(pmc_id) or pmc_available[paper_id] is not True:
            _reject()
    elif status == "no_link":
        if pmc_id is not None or pmc_available[paper_id] is not False:
            _reject()
    else:
        _reject()


def _validate_one_batch(  # noqa: C901
    batch: Any,
    *,
    batch_index: int,
    expected_ids: list[str],
    pmc_available: dict[str, bool],
) -> None:
    if not isinstance(batch, dict) or set(batch) != _BATCH_FIELDS:
        _reject()
    if (
        type(batch.get("batch_index")) is not int
        or batch["batch_index"] != batch_index
        or batch.get("input_pmids") != expected_ids
        or len(expected_ids) > _BATCH_SIZE
        or batch.get("cache_hit_pmids") != []
        or batch.get("efetch_pmids") != expected_ids
        or batch.get("elink_pmids") != expected_ids
    ):
        _reject()
    returned = batch.get("efetch_returned_pmids")
    if (
        not isinstance(returned, list)
        or any(not _is_pmid(pmid) for pmid in returned)
        or len(returned) != len(expected_ids)
        or len(set(returned)) != len(returned)
        or set(returned) != set(expected_ids)
    ):
        _reject()
    link_results = batch.get("elink_results")
    if not isinstance(link_results, list) or len(link_results) != len(
        expected_ids
    ):
        _reject()
    for paper_id, result in zip(expected_ids, link_results, strict=True):
        _validate_link_result(result, paper_id, pmc_available)


def _validate_batches(
    trace: dict[str, Any],
    selected_ids: list[str],
    pmc_available: dict[str, bool],
) -> tuple[int, int]:
    batching = trace.get("metadata_batching")
    if not isinstance(batching, dict) or set(batching) != {
        "sampled_pmids",
        "cache_hits",
        "batches",
    }:
        _reject()
    if (
        batching.get("sampled_pmids") != selected_ids
        or batching.get("cache_hits") != []
    ):
        _reject()
    batches = batching.get("batches")
    expected_count = (len(selected_ids) + _BATCH_SIZE - 1) // _BATCH_SIZE
    if not isinstance(batches, list) or len(batches) != expected_count:
        _reject()
    for index, batch in enumerate(batches):
        start = index * _BATCH_SIZE
        _validate_one_batch(
            batch,
            batch_index=index + 1,
            expected_ids=selected_ids[start : start + _BATCH_SIZE],
            pmc_available=pmc_available,
        )
    metadata_efetch_batches = sum(
        bool(batch["efetch_pmids"]) for batch in batches
    )
    elink_batches = sum(bool(batch["elink_pmids"]) for batch in batches)
    return metadata_efetch_batches, elink_batches


def _validate_batch_call_counts(
    calls: dict[str, int], metadata_efetch_batches: int, elink_batches: int
) -> None:
    if (
        calls["efetch"] < metadata_efetch_batches
        or calls["elink"] != elink_batches
    ):
        _reject()


def _sanitized_evidence(
    trace: dict[str, Any],
    selected_ids: list[str],
    metadata_efetch_batches: int,
    elink_batches: int,
) -> dict[str, Any]:
    per_pmid_baseline = len(selected_ids)
    return {
        "entrez_retry_policy": _RETRY_POLICY.copy(),
        "entrez_calls": trace["entrez_calls"].copy(),
        "incomplete_fetch_count": 0,
        "fetch_errors": [],
        "metadata_origins": trace["metadata_origins"].copy(),
        "selected_pmids": list(selected_ids),
        "metadata_batching": {
            "sampled_pmids": list(selected_ids),
            "cache_hits": [],
            "batch_count": metadata_efetch_batches,
            "metadata_efetch_batches": metadata_efetch_batches,
            "elink_batches": elink_batches,
        },
        "metadata_savings": {
            "per_pmid_efetch_baseline": per_pmid_baseline,
            "metadata_efetch_batches": metadata_efetch_batches,
            "efetch_entries_saved": per_pmid_baseline - metadata_efetch_batches,
            "per_pmid_elink_baseline": per_pmid_baseline,
            "elink_batches": elink_batches,
            "elink_entries_saved": per_pmid_baseline - elink_batches,
        },
        "count_semantics": {
            "entrez_calls": (
                "Maintained Entrez wrapper entries; aggregate EFetch includes "
                "metadata batches and may include PMC fulltext pagination."
            ),
            "metadata_savings": (
                "Per-PMID metadata EFetch/ELink baseline versus validated "
                "metadata batch entries only; excludes search, fulltext, "
                "recovery, and physical HTTP request counts."
            ),
        },
    }


def validate_batch_trace(
    trace: dict[str, Any],
    *,
    run_id: str,
    expected_build_id: str,
    serving_process: dict[str, Any],
    returned_ids: list[str] | None,
) -> dict[str, Any]:
    """Validates batch metadata accounting without rewriting raw trace data."""
    if not isinstance(trace, dict) or not isinstance(serving_process, dict):
        _reject()
    _validate_identity(
        trace,
        run_id=run_id,
        expected_build_id=expected_build_id,
        serving_process=serving_process,
    )
    _validate_recovery_fields(trace, serving_process)
    calls = _validated_calls(trace)
    selected_ids = _search_selection(trace, calls)
    _validate_pool_and_errors(trace)
    pmc_available = _fetched_pmc_availability(trace, selected_ids)
    _validate_final_ids(
        trace,
        selected_ids=selected_ids,
        returned_ids=returned_ids,
    )
    if not selected_ids:
        _validate_empty_trace(trace, calls)
        metadata_efetch_batches = elink_batches = 0
    else:
        metadata_efetch_batches, elink_batches = _validate_batches(
            trace, selected_ids, pmc_available
        )
        _validate_batch_call_counts(
            calls, metadata_efetch_batches, elink_batches
        )
    return _sanitized_evidence(
        trace, selected_ids, metadata_efetch_batches, elink_batches
    )


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
    """Validate and return one bounded v4 retry ledger delta."""

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
