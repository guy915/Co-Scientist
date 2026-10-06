import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from Bio import Entrez

from mcp_server.entrez import (
    entrez_call,
    pilot_trace_context,
    record_pilot_fetch_error,
    record_pilot_metadata_origin,
)
from mcp_server.pubmed_client import (
    PUBMED_METADATA_BATCH_SIZE,
    _EntrezClient,
    _parse_pubmed_article,
)
from mcp_server.pubmed_pilot_trace import record_pubmed_batch_outcome
from mcp_server.pubmed_storage import (
    has_proven_metadata_no_link,
    link_metadata_to_run,
    write_metadata_cache_file,
)

logger = logging.getLogger(__name__)


@dataclass
class _BatchCache:
    cached: dict[str, dict[str, Any]]
    proven_no_link: set[str]
    cache_hits: list[str]
    fetch_ids: list[str]


@dataclass(frozen=True)
class _BatchContext:
    client: _EntrezClient
    shared_dir: Path
    run_dir: Path | None
    semaphore: asyncio.Semaphore


@dataclass
class _FetchedBatch:
    metadata: dict[str, dict[str, Any]]
    returned_ids: list[str]
    metadata_errors: dict[str, Exception]
    link_outcomes: dict[str, tuple[str | None, Exception | None]]
    attempted_elink_ids: list[str]


def _valid_link_id(link: Any) -> bool:
    link_id = link.get("Id") if isinstance(link, dict) else None
    return (
        not isinstance(link_id, bool)
        and isinstance(link_id, (str, int))
        and str(link_id).isascii()
        and str(link_id).isdecimal()
    )


def _valid_link_item(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("LinkName"), str)
        and bool(item["LinkName"])
        and isinstance(item.get("Link"), list)
        and all(_valid_link_id(link) for link in item["Link"])
    )


def _index_link_groups(
    related: list[Any], requested: set[str]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Exception]]:
    groups_by_id: dict[str, list[dict[str, Any]]] = {}
    group_errors: dict[str, Exception] = {}
    for group in related:
        if not isinstance(group, dict) or not isinstance(source_ids := group.get("IdList"), list):
            continue
        error = ValueError("ELink group does not identify one PMID")
        for paper_id in requested.intersection(map(str, source_ids)):
            if len(source_ids) == 1:
                groups_by_id.setdefault(paper_id, []).append(group)
            else:
                group_errors[paper_id] = error
    return groups_by_id, group_errors


def _parse_pmc_link_group(
    group: dict[str, Any],
) -> tuple[str | None, Exception | None]:
    if "LinkSetDb" not in group:
        return None, None
    link_set_db = group["LinkSetDb"]
    if not isinstance(link_set_db, list) or not all(_valid_link_item(item) for item in link_set_db):
        return None, ValueError("ELink PMID group has malformed link records")
    pmc_groups = [item for item in link_set_db if item["LinkName"] == "pubmed_pmc"]
    if len(pmc_groups) > 1:
        return None, ValueError("ELink PMID group has duplicate pubmed_pmc links")
    if not pmc_groups or not pmc_groups[0]["Link"]:
        return None, None
    return str(pmc_groups[0]["Link"][0]["Id"]), None


def _map_pmc_link_groups(
    related: Any, paper_ids: list[str]
) -> dict[str, tuple[str | None, Exception | None]]:
    """ELink groups are keyed by source PMID; response order is not an
    identity contract.
    """
    requested = set(paper_ids)
    if not isinstance(related, list):
        error = ValueError("ELink response is not a group list")
        return dict.fromkeys(paper_ids, (None, error))
    groups_by_id, group_errors = _index_link_groups(related, requested)

    outcomes: dict[str, tuple[str | None, Exception | None]] = {}
    for paper_id in paper_ids:
        if paper_id in group_errors:
            outcomes[paper_id] = (None, group_errors[paper_id])
            continue
        groups = groups_by_id.get(paper_id, [])
        if len(groups) != 1:
            reason = "missing" if not groups else "duplicate"
            outcomes[paper_id] = (
                None,
                ValueError(f"ELink response has a {reason} PMID group"),
            )
            continue
        outcomes[paper_id] = _parse_pmc_link_group(groups[0])
    return outcomes


def _fetch_pmc_fulltext_ids(
    client: _EntrezClient, paper_ids: list[str]
) -> dict[str, tuple[str | None, Exception | None]]:
    if not paper_ids:
        return {}
    try:
        related = client.entrez_read(
            entrez_call(
                Entrez.elink,
                dbfrom="pubmed",
                db="pmc",
                linkname="pubmed_pmc",
                id=paper_ids,
            )
        )
    except Exception as exc:
        return dict.fromkeys(paper_ids, (None, exc))
    return _map_pmc_link_groups(related, paper_ids)


def _group_pubmed_records(
    records: list[Any], paper_ids: list[str]
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    requested = set(paper_ids)
    records_by_id: dict[str, list[dict[str, Any]]] = {}
    returned_ids: list[str] = []
    for record in records:
        try:
            paper_id = str(record["MedlineCitation"]["PMID"])
        except (KeyError, TypeError):
            continue
        if paper_id in requested:
            returned_ids.append(paper_id)
            records_by_id.setdefault(paper_id, []).append(record)
    return records_by_id, returned_ids


def _parse_pubmed_record_group(
    records: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, Exception | None]:
    if len(records) != 1:
        reason = "missing" if not records else "duplicate"
        return None, ValueError(f"PubMed EFetch response has a {reason} PMID record")
    try:
        return _parse_pubmed_article(records[0], None), None
    except Exception as exc:
        return None, exc


def _fetch_paper_details(
    client: _EntrezClient, paper_ids: list[str]
) -> tuple[dict[str, dict[str, Any]], list[str], dict[str, Exception]]:
    if not paper_ids:
        return {}, [], {}
    try:
        results = client.entrez_read(
            entrez_call(Entrez.efetch, db="pubmed", id=paper_ids, retmode="xml")
        )
        records = results["PubmedArticle"]
        if not isinstance(records, list):
            raise ValueError("PubMed EFetch response is not an article list")
    except Exception as exc:
        return {}, [], dict.fromkeys(paper_ids, exc)

    return _parse_pubmed_batch(records, paper_ids)


def _parse_pubmed_batch(
    records: list[Any], paper_ids: list[str]
) -> tuple[dict[str, dict[str, Any]], list[str], dict[str, Exception]]:
    records_by_id, returned_ids = _group_pubmed_records(records, paper_ids)
    metadata: dict[str, dict[str, Any]] = {}
    errors: dict[str, Exception] = {}
    for paper_id in paper_ids:
        details, error = _parse_pubmed_record_group(records_by_id.get(paper_id, []))
        if error is not None:
            errors[paper_id] = error
        elif details is not None:
            metadata[paper_id] = details
    return metadata, returned_ids, errors


def _fetch_metadata_batch(
    client: _EntrezClient, fetch_ids: list[str], elink_ids: list[str]
) -> _FetchedBatch:
    metadata, returned_ids, metadata_errors = _fetch_paper_details(client, fetch_ids)
    attempted_elink_ids = [
        paper_id for paper_id in elink_ids if paper_id not in fetch_ids or paper_id in metadata
    ]
    links = _fetch_pmc_fulltext_ids(client, attempted_elink_ids)
    return _FetchedBatch(
        metadata,
        returned_ids,
        metadata_errors,
        links,
        attempted_elink_ids,
    )


def _read_batch_cache(context: _BatchContext, paper_ids: list[str]) -> _BatchCache:
    cached: dict[str, dict[str, Any]] = {}
    proven_no_link: set[str] = set()
    cache_hits: list[str] = []
    fetch_ids: list[str] = []
    for paper_id in paper_ids:
        metadata_file = context.shared_dir / f"{paper_id}.metadata.json"
        if not metadata_file.exists():
            fetch_ids.append(paper_id)
            continue
        with open(metadata_file, encoding="utf-8") as stream:
            metadata = json.load(stream)
        is_no_link = not metadata.get("pmc_full_text_id")
        if is_no_link and has_proven_metadata_no_link(metadata_file):
            proven_no_link.add(paper_id)
        cached[paper_id] = metadata
        cache_hits.append(paper_id)
        with pilot_trace_context(None, paper_id):
            record_pilot_metadata_origin(paper_id, "shared_pool_cache")
        link_metadata_to_run(context.run_dir, paper_id)
    return _BatchCache(cached, proven_no_link, cache_hits, fetch_ids)


def _write_batch_metadata(context: _BatchContext, paper_id: str, metadata: dict[str, Any]) -> None:
    metadata_file = context.shared_dir / f"{paper_id}.metadata.json"
    write_metadata_cache_file(
        metadata_file,
        metadata,
        successful_no_link=not metadata.get("pmc_full_text_id"),
    )
    link_metadata_to_run(context.run_dir, paper_id)
    logger.debug("Saved metadata for %s to shared pool", paper_id)


def _metadata_for_batch_item(
    paper_id: str,
    cache: _BatchCache,
    fetched: _FetchedBatch,
) -> dict[str, Any] | None:
    if paper_id in cache.cached:
        return cache.cached[paper_id]
    error = fetched.metadata_errors.get(paper_id)
    if error is not None:
        with pilot_trace_context(None, paper_id):
            record_pilot_fetch_error("metadata_fetch", error)
        return None
    with pilot_trace_context(None, paper_id):
        record_pilot_metadata_origin(paper_id, "entrez_fetch")
    return fetched.metadata[paper_id]


def _process_batch_metadata(
    context: _BatchContext,
    paper_id: str,
    cache: _BatchCache,
    fetched: _FetchedBatch,
) -> dict[str, Any] | None:
    details = _metadata_for_batch_item(paper_id, cache, fetched)
    if details is None:
        return None
    link_outcome = fetched.link_outcomes.get(paper_id)
    if link_outcome is not None and link_outcome[1] is not None:
        error = link_outcome[1]
        stage = (
            "elink_parse"
            if isinstance(error, (ValueError, KeyError, TypeError, IndexError))
            else "elink"
        )
        with pilot_trace_context(None, paper_id):
            record_pilot_fetch_error(stage, error)
        details = dict(details)
        details["pmc_full_text_id"] = None
        return details
    if link_outcome is not None:
        details = dict(details)
        details["pmc_full_text_id"] = link_outcome[0]
    if paper_id not in cache.cached or link_outcome is not None:
        _write_batch_metadata(context, paper_id, details)
    return details


def _valid_ordered_pmids(paper_ids: list[str]) -> list[str]:
    ordered_ids: list[str] = []
    seen: set[str] = set()
    for paper_id in paper_ids:
        if not isinstance(paper_id, str) or not paper_id.isascii() or not paper_id.isdecimal():
            record_pilot_fetch_error(
                "metadata_input",
                ValueError("PubMed ID must contain ASCII digits only"),
                paper_id if isinstance(paper_id, str) else None,
            )
            continue
        if paper_id not in seen:
            seen.add(paper_id)
            ordered_ids.append(paper_id)
    return ordered_ids


async def gather_metadata(
    client: _EntrezClient,
    paper_ids: list[str],
    shared_dir: Path,
    run_dir: Path | None,
    semaphore: "asyncio.Semaphore",
) -> dict[str, dict[str, Any]]:
    ordered_ids = _valid_ordered_pmids(paper_ids)
    batches = [
        ordered_ids[index : index + PUBMED_METADATA_BATCH_SIZE]
        for index in range(0, len(ordered_ids), PUBMED_METADATA_BATCH_SIZE)
    ]
    context = _BatchContext(client, shared_dir, run_dir, semaphore)
    results = await asyncio.gather(
        *[
            _fetch_metadata_batch_async(context, batch, index + 1)
            for index, batch in enumerate(batches)
        ]
    )
    details_by_id = {
        paper_id: metadata
        for batch_result in results
        for paper_id, metadata in batch_result.items()
    }
    return {
        paper_id: details_by_id[paper_id] for paper_id in ordered_ids if paper_id in details_by_id
    }


async def _fetch_metadata_batch_async(
    context: _BatchContext,
    paper_ids: list[str],
    batch_index: int,
) -> dict[str, dict[str, Any]]:
    cache = _read_batch_cache(context, paper_ids)
    elink_ids = [
        paper_id
        for paper_id in paper_ids
        if paper_id in cache.fetch_ids
        or (
            not cache.cached.get(paper_id, {}).get("pmc_full_text_id")
            and paper_id not in cache.proven_no_link
        )
    ]
    with pilot_trace_context(None, paper_ids[0] if paper_ids else None):
        async with context.semaphore:
            fetched = await asyncio.to_thread(
                _fetch_metadata_batch,
                context.client,
                cache.fetch_ids,
                elink_ids,
            )

    results: dict[str, dict[str, Any]] = {}
    for paper_id in paper_ids:
        details = _process_batch_metadata(context, paper_id, cache, fetched)
        if details is not None:
            results[paper_id] = details
    record_pubmed_batch_outcome(
        {
            "batch_index": batch_index,
            "input_pmids": paper_ids,
            "cache_hit_pmids": cache.cache_hits,
            "efetch_pmids": cache.fetch_ids,
            "efetch_returned_pmids": fetched.returned_ids,
            "elink_pmids": fetched.attempted_elink_ids,
        },
        fetched.link_outcomes,
    )
    return results
