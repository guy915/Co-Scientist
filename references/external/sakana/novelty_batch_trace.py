"""Strict, offline validation for the maintained PubMed batch trace."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn, cast

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
    raise ValueError("PubMed batch trace attestation is incomplete or inconsistent")


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
    if not isinstance(calls, dict) or set(calls) != {"esearch", "efetch", "elink"}:
        _reject()
    if any(type(value) is not int or value < 0 for value in calls.values()):
        _reject()
    return calls


def _search_selection(trace: dict[str, Any], calls: dict[str, int]) -> list[str]:
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
    if "metadata_batching" in trace or calls["efetch"] != 0 or calls["elink"] != 0:
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
        or [row.get("pmid") for row in fetched if isinstance(row, dict)] != selected_ids
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
    if recovery_fields.intersection(trace) or "study4_recovery" in serving_process:
        _reject()


def _validate_link_result(
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


def _validate_one_batch(
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
    if not isinstance(link_results, list) or len(link_results) != len(expected_ids):
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
    metadata_efetch_batches = sum(bool(batch["efetch_pmids"]) for batch in batches)
    elink_batches = sum(bool(batch["elink_pmids"]) for batch in batches)
    return metadata_efetch_batches, elink_batches


def _validate_batch_call_counts(
    calls: dict[str, int], metadata_efetch_batches: int, elink_batches: int
) -> None:
    if calls["efetch"] < metadata_efetch_batches or calls["elink"] != elink_batches:
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
        _validate_batch_call_counts(calls, metadata_efetch_batches, elink_batches)
    return _sanitized_evidence(
        trace, selected_ids, metadata_efetch_batches, elink_batches
    )
