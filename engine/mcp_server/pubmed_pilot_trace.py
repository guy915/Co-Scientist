"""Bounded, opt-in provenance for maintained PubMed pilot runs."""

import heapq
import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast

from Bio import Entrez

import mcp_server.pubmed_client as pubmed_client
from mcp_server.entrez import (
    PILOT_ENTREZ_MAX_TRIES,
    PILOT_ENTREZ_SLEEP_BETWEEN_TRIES,
    STUDY4_MAX_RETRIES_PER_LOGICAL_REQUEST,
    STUDY4_MAX_RETRIES_PER_STUDY,
    STUDY4_RECOVERY_POLICY,
    STUDY4_RECOVERY_STUDY_ID,
    _pilot_trace_context,
    _pilot_trace_lock,
    bind_study4_recovery,
)
from mcp_server.pubmed_client import PUBMED_SEARCH_SORT

_MAX_PILOT_TRACE_IDS = 9


def record_metadata_batch(batch: dict[str, Any]) -> None:
    """Records selected PMID batch provenance within the pilot trace bounds."""
    context = _pilot_trace_context.get()
    if context is None:
        return
    trace, _paper_id = context
    selected_ids, selected_omitted = _selected_metadata_ids(trace)
    input_ids = batch.get("input_pmids", [])
    if not _batch_contains_selected(input_ids, selected_ids):
        return

    batch_record = _bounded_batch_record(batch)
    with _pilot_trace_lock:
        batching = _batching_trace(trace, selected_ids, selected_omitted)
        _record_cache_hits(
            batching, batch.get("cache_hit_pmids", []), selected_ids
        )
        _append_bounded_batch(batching, batch_record)


def record_pubmed_batch_outcome(
    batch: dict[str, Any],
    link_outcomes: dict[str, tuple[str | None, Exception | None]],
) -> None:
    """Records a batch result using bounded pilot-trace semantics."""
    batch["elink_results"] = [
        _metadata_link_trace(paper_id, link_outcomes[paper_id])
        for paper_id in batch["elink_pmids"]
    ]
    record_metadata_batch(batch)


def _metadata_link_trace(
    paper_id: str, outcome: tuple[str | None, Exception | None]
) -> dict[str, str | None]:
    pmc_id, error = outcome
    status = "error" if error else "linked" if pmc_id else "no_link"
    return {"pmid": paper_id, "status": status, "pmc_id": pmc_id}


def _selected_metadata_ids(trace: dict[str, Any]) -> tuple[list[str], int]:
    selected = trace.get("selected")
    if not isinstance(selected, dict) or not isinstance(
        selected.get("ids"), list
    ):
        return [], 0
    ids = selected["ids"]
    return ids[:_MAX_PILOT_TRACE_IDS], max(0, len(ids) - _MAX_PILOT_TRACE_IDS)


def _batch_contains_selected(input_ids: Any, selected_ids: list[str]) -> bool:
    return isinstance(input_ids, list) and any(
        paper_id in selected_ids for paper_id in input_ids
    )


def _bounded_batch_record(batch: dict[str, Any]) -> dict[str, Any]:
    batch_record: dict[str, Any] = {}
    truncated: dict[str, int] = {}
    for key, value in batch.items():
        if not isinstance(value, list):
            batch_record[key] = value
            continue
        batch_record[key] = value[:_MAX_PILOT_TRACE_IDS]
        omitted = len(value) - _MAX_PILOT_TRACE_IDS
        if omitted > 0:
            truncated[key] = omitted
    if truncated:
        batch_record["truncated_members"] = truncated
    return batch_record


def _batching_trace(
    trace: dict[str, Any], selected_ids: list[str], selected_omitted: int
) -> dict[str, Any]:
    batching = trace.setdefault(
        "metadata_batching",
        {"sampled_pmids": selected_ids, "cache_hits": [], "batches": []},
    )
    if selected_omitted:
        batching["truncated_sampled_pmids"] = selected_omitted
    return cast(dict[str, Any], batching)


def _record_cache_hits(
    batching: dict[str, Any], cache_hits: Any, selected_ids: list[str]
) -> None:
    if not isinstance(cache_hits, list):
        return
    sampled_hits = batching["cache_hits"]
    for paper_id in cache_hits:
        if paper_id not in selected_ids or paper_id in sampled_hits:
            continue
        if len(sampled_hits) < _MAX_PILOT_TRACE_IDS:
            sampled_hits.append(paper_id)
        else:
            batching["truncated_cache_hits"] = (
                batching.get("truncated_cache_hits", 0) + 1
            )


def _append_bounded_batch(
    batching: dict[str, Any], batch_record: dict[str, Any]
) -> None:
    if len(batching["batches"]) < _MAX_PILOT_TRACE_IDS:
        batching["batches"].append(batch_record)
    else:
        batching["truncated_batches"] = batching.get("truncated_batches", 0) + 1


def _pilot_trace_flags() -> tuple[bool, bool]:
    trace_enabled = os.getenv("COSCIENTIST_PUBMED_PILOT_TRACE") == "1"
    recovery_setting = os.getenv("COSCIENTIST_PUBMED_STUDY4_RECOVERY", "0")
    if recovery_setting not in {"0", "1"}:
        raise ValueError("Study 4 Entrez recovery flag must be 0 or 1")
    recovery_enabled = recovery_setting == "1"
    if recovery_enabled and not trace_enabled:
        raise ValueError("Study 4 Entrez recovery requires pilot tracing")
    return trace_enabled, recovery_enabled


def _enable_study4_recovery(trace: dict[str, Any]) -> None:
    study_id = os.getenv("COSCIENTIST_PUBMED_STUDY_ID")
    if study_id != STUDY4_RECOVERY_STUDY_ID:
        raise ValueError(
            "Study 4 Entrez recovery requires the protocol study ID"
        )
    process_retries_used = bind_study4_recovery(study_id)
    trace.update(
        {
            "entrez_recovery": {
                "study_id": study_id,
                "policy": STUDY4_RECOVERY_POLICY,
                "max_retries_per_logical_request": (
                    STUDY4_MAX_RETRIES_PER_LOGICAL_REQUEST
                ),
                "max_retries_per_study": STUDY4_MAX_RETRIES_PER_STUDY,
                "retries_used": 0,
                "recovered_calls": 0,
                "exhausted_calls": 0,
                "client_entry_attempts": {
                    "esearch": 0,
                    "efetch": 0,
                    "elink": 0,
                },
                "process_retries_used_at_start": process_retries_used,
                "process_retries_used_at_end": process_retries_used,
            },
            "recovered_transient_attempts": [],
            "entrez_recovery_call_outcomes": [],
        }
    )


def new_pilot_trace(run_id: str | None) -> dict[str, Any] | None:
    """Creates provenance only when an explicit pilot trace is requested."""
    trace_enabled, recovery_enabled = _pilot_trace_flags()
    if not trace_enabled:
        return None
    build_id = os.getenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID")
    if not run_id or not build_id:
        raise ValueError("PubMed pilot tracing requires run_id and build_id")
    # This environment flag denotes an isolated trace-only serving process:
    # pin Biopython's hidden retry loop before any request and record the
    # effective values so a pilot cannot mistake its rung count for wire calls.
    Entrez.max_tries = PILOT_ENTREZ_MAX_TRIES
    Entrez.sleep_between_tries = PILOT_ENTREZ_SLEEP_BETWEEN_TRIES
    trace: dict[str, Any] = {
        "run_id": run_id,
        "server_build_id": build_id,
        "process_id": os.getpid(),
        "source_file": str(Path(pubmed_client.__file__).resolve()),
        "sort": PUBMED_SEARCH_SORT,
        "entrez_retry_policy": {
            "max_tries": Entrez.max_tries,
            "sleep_between_tries": Entrez.sleep_between_tries,
        },
        "entrez_calls": {"esearch": 0, "efetch": 0, "elink": 0},
        "incomplete_fetch_count": 0,
        "fetch_errors": [],
        "metadata_origins": {},
        "attempts": [],
        "selected": None,
        "fetched": [],
        "final_ids": [],
        "shared_pool_supplements": [],
        "error": None,
    }
    if recovery_enabled:
        _enable_study4_recovery(trace)
    return trace


def record_pool_snapshot(
    trace: dict[str, Any] | None, shared_dir: Path
) -> None:
    """Records bounded shared-pool counts and pre-search identifiers."""
    if trace is None:
        return
    metadata_count = sum(1 for _ in shared_dir.glob("*.metadata.json"))
    first_metadata_files = heapq.nsmallest(
        _MAX_PILOT_TRACE_IDS, shared_dir.glob("*.metadata.json")
    )
    trace["pre_search_shared_pool"] = {
        "file_count": sum(1 for _ in shared_dir.iterdir()),
        "metadata_count": metadata_count,
        "first_ids": [
            path.name.removesuffix(".metadata.json")
            for path in first_metadata_files
        ],
    }


def _abstract_available(metadata: dict[str, Any] | None) -> bool:
    if metadata is None:
        return False
    abstract = metadata.get("abstract")
    return (
        isinstance(abstract, str)
        and bool(abstract.strip())
        and (abstract.strip() != "<not found>")
    )


def record_fetched_papers(
    trace: dict[str, Any], all_details: dict[str, Any]
) -> None:
    """Records fetch and availability outcomes for selected search IDs."""
    selected = trace.get("selected")
    selected_ids = selected["ids"] if isinstance(selected, dict) else []
    fetch_errors = trace.get("fetch_errors", [])
    metadata_origins = trace.get("metadata_origins", {})
    trace["fetched"] = [
        {
            "pmid": paper_id,
            "fetched": paper_id in all_details,
            "metadata_origin": metadata_origins.get(paper_id),
            "pmc_available": bool(
                all_details.get(paper_id, {}).get("pmc_full_text_id")
            ),
            "abstract_available": _abstract_available(
                all_details.get(paper_id)
            ),
            "incomplete": paper_id not in all_details
            or any(error.get("pmid") == paper_id for error in fetch_errors),
        }
        for paper_id in selected_ids[:_MAX_PILOT_TRACE_IDS]
    ]


def reserve_trace_run(run_dir: Path, run_id: str, build_id: str) -> None:
    """Exclusively reserves a clean run directory before any Entrez request."""
    if any(run_dir.iterdir()):
        raise ValueError(
            "PubMed pilot trace run_id is not empty or already reserved"
        )
    reservation_path = run_dir / ".trace-reservation.json"
    try:
        descriptor = os.open(
            reservation_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as exc:
        raise ValueError(
            "PubMed pilot trace run_id is not empty or already reserved"
        ) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                {
                    "run_id": run_id,
                    "server_build_id": build_id,
                    "process_id": os.getpid(),
                },
                stream,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        reservation_path.unlink(missing_ok=True)
        raise


def write_trace_atomically(path: Path, trace: dict[str, Any]) -> None:
    """Publishes a private same-directory trace without replacing prior runs."""
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=".search-trace-", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(trace, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Publish a complete same-directory file and reject reused run ids.
        os.link(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
