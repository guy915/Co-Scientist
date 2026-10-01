"""Convert research findings into provenance-stamped evidence records."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from co_scientist.research import Finding, ResearchResult

if TYPE_CHECKING:
    from co_scientist.research_adapter import ResearchRetrieval


def records_from_findings(
    result: ResearchResult, retrieval: ResearchRetrieval
) -> dict[str, dict[str, Any]]:
    """Turn the papers that produced findings into review-shaped records.

    Generation and Reflection share the same article pool and provenance
    shape, so neither agent owns this conversion.

    Only documents something was actually drawn from are carried over: a
    hit the loop searched up but read nothing useful from is already on
    record in the ledger, and adding it to the paper pool would put a
    document into every downstream prompt on the strength of having
    appeared in a result list.

    Each record is stamped with the id of the call that surfaced it,
    which is what lets a caller persisting the article say which query
    found it and which question that query was serving.
    """
    records: dict[str, dict[str, Any]] = {}
    for finding in result.findings:
        if finding.locator in records:
            continue
        record = retrieval.record(finding.locator)
        if record is None:
            continue
        record["retrieval_call_id"] = finding.call_id
        record.setdefault("_source_name", _source_of(result, finding))
        records[finding.locator] = record
    return records


def _source_of(result: ResearchResult, finding: Finding) -> str:
    """Name the source whose call surfaced one finding."""
    for call in result.calls:
        if call.id == finding.call_id:
            return call.source
    return ""
