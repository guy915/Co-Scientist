"""Bounded, opt-in provenance for maintained PubMed pilot runs."""

import heapq
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from Bio import Entrez

import mcp_server.pubmed_client as pubmed_client
from mcp_server.entrez_rate_limit import (
    PILOT_ENTREZ_MAX_TRIES,
    PILOT_ENTREZ_SLEEP_BETWEEN_TRIES,
)
from mcp_server.pubmed_client import PUBMED_SEARCH_SORT

_MAX_PILOT_TRACE_IDS = 9


def new_pilot_trace(run_id: str | None) -> dict[str, Any] | None:
    """Creates provenance only when an explicit pilot trace is requested."""
    if os.getenv("COSCIENTIST_PUBMED_PILOT_TRACE") != "1":
        return None
    build_id = os.getenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID")
    if not run_id or not build_id:
        raise ValueError("PubMed pilot tracing requires run_id and build_id")
    # This environment flag denotes an isolated trace-only serving process:
    # pin Biopython's hidden retry loop before any request and record the
    # effective values so a pilot cannot mistake its rung count for wire calls.
    Entrez.max_tries = PILOT_ENTREZ_MAX_TRIES
    Entrez.sleep_between_tries = PILOT_ENTREZ_SLEEP_BETWEEN_TRIES
    return {
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
