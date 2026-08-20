"""Turning a research result into plain data, and back.

A caller that persists anything has to get this result across a boundary
that only carries JSON -- a checkpoint, a task payload, a store row. The
artifacts are frozen dataclasses holding enums and tuples, so
``dataclasses.asdict`` alone produces something that will not survive the
trip: an ``Enum`` member is not JSON, and a tuple comes back a list.

Hence an explicit pair. ``result_to_dict`` writes enums as their values
and every sequence as a list; ``result_from_dict`` reads that back into
the same artifacts, so the ids re-derive identically and a resumed run
still recognises the work it paid for.

Unknown keys are ignored and missing ones take their dataclass default,
so a payload written by an older build still loads. Ids are deliberately
*not* written: they are derived from content, and storing them would
allow a payload whose stored id disagrees with what its fields hash to.
"""

from __future__ import annotations

from typing import Any

from co_scientist.research.artifacts import (
    CallStatus,
    Finding,
    Question,
    ResearchResult,
    SearchCall,
    SourceHit,
    StopReason,
    ThreadRecord,
    ThreadStatus,
)


def result_to_dict(result: ResearchResult) -> dict[str, Any]:
    """Render a research result as JSON-safe plain data.

    Args:
        result: What ``conduct_research`` returned.

    Returns:
        A dict of lists, strings and numbers, round-trippable by
        :func:`result_from_dict`.
    """
    return {
        "goal": result.goal,
        "stances": list(result.stances),
        "threads": [_thread_to_dict(thread) for thread in result.threads],
        "calls": [_call_to_dict(call) for call in result.calls],
        "findings": [_finding_to_dict(f) for f in result.findings],
        "stop_reason": result.stop_reason.value,
        "levels_run": result.levels_run,
    }


def result_from_dict(data: dict[str, Any]) -> ResearchResult:
    """Rebuild a research result from :func:`result_to_dict` output.

    Args:
        data: A payload written by ``result_to_dict``.

    Returns:
        The result, with every id re-derived from its content.
    """
    return ResearchResult(
        goal=str(data.get("goal", "")),
        stances=tuple(_strings(data.get("stances"))),
        threads=tuple(
            _thread_from_dict(item) for item in _dicts(data.get("threads"))
        ),
        calls=tuple(
            _call_from_dict(item) for item in _dicts(data.get("calls"))
        ),
        findings=tuple(
            _finding_from_dict(item) for item in _dicts(data.get("findings"))
        ),
        stop_reason=_enum(
            StopReason, data.get("stop_reason"), StopReason.DEPTH_EXHAUSTED
        ),
        levels_run=int(data.get("levels_run") or 0),
    )


def _thread_to_dict(thread: ThreadRecord) -> dict[str, Any]:
    """Render one thread record."""
    return {
        "question": {
            "text": thread.question.text,
            "stance": thread.question.stance,
            "parent_id": thread.question.parent_id,
        },
        "depth": thread.depth,
        "status": thread.status.value,
        "call_ids": list(thread.call_ids),
        "finding_ids": list(thread.finding_ids),
        "follow_ups": list(thread.follow_ups),
        "summary": thread.summary,
        "note": thread.note,
        "retry_breadth": thread.retry_breadth,
    }


def _thread_from_dict(data: dict[str, Any]) -> ThreadRecord:
    """Read one thread record back."""
    asked = data.get("question")
    asked = asked if isinstance(asked, dict) else {}
    return ThreadRecord(
        question=Question(
            text=str(asked.get("text", "")),
            stance=str(asked.get("stance", "")),
            parent_id=_optional_str(asked.get("parent_id")),
        ),
        depth=int(data.get("depth") or 0),
        status=_enum(ThreadStatus, data.get("status"), ThreadStatus.OK),
        call_ids=tuple(_strings(data.get("call_ids"))),
        finding_ids=tuple(_strings(data.get("finding_ids"))),
        follow_ups=tuple(_strings(data.get("follow_ups"))),
        summary=_optional_str(data.get("summary")),
        note=_optional_str(data.get("note")),
        retry_breadth=_optional_int(data.get("retry_breadth")),
    )


def _call_to_dict(call: SearchCall) -> dict[str, Any]:
    """Render one search call, ranking included."""
    return {
        "question": call.question,
        "query": call.query,
        "source": call.source,
        "status": call.status.value,
        "hits": [_hit_to_dict(hit) for hit in call.hits],
        "admitted": list(call.admitted),
        "dropped": list(call.dropped),
        "error": call.error,
        "duration_seconds": call.duration_seconds,
    }


def _call_from_dict(data: dict[str, Any]) -> SearchCall:
    """Read one search call back."""
    return SearchCall(
        question=str(data.get("question", "")),
        query=str(data.get("query", "")),
        source=str(data.get("source", "")),
        status=_enum(CallStatus, data.get("status"), CallStatus.OK),
        hits=tuple(_hit_from_dict(item) for item in _dicts(data.get("hits"))),
        admitted=tuple(_strings(data.get("admitted"))),
        dropped=tuple(_strings(data.get("dropped"))),
        error=_optional_str(data.get("error")),
        duration_seconds=_optional_float(data.get("duration_seconds")),
    )


def _hit_to_dict(hit: SourceHit) -> dict[str, Any]:
    """Render one hit as the source returned it."""
    return {
        "locator": hit.locator,
        "title": hit.title,
        "snippet": hit.snippet,
        "rank": hit.rank,
        "score": hit.score,
        "metadata": dict(hit.metadata),
    }


def _hit_from_dict(data: dict[str, Any]) -> SourceHit:
    """Read one hit back."""
    metadata = data.get("metadata")
    return SourceHit(
        locator=str(data.get("locator", "")),
        title=str(data.get("title", "")),
        snippet=str(data.get("snippet", "")),
        rank=int(data.get("rank") or 0),
        score=_optional_float(data.get("score")),
        metadata={
            str(key): str(value)
            for key, value in (
                metadata.items() if isinstance(metadata, dict) else ()
            )
        },
    )


def _finding_to_dict(finding: Finding) -> dict[str, Any]:
    """Render one finding, bound to the call that surfaced it."""
    return {
        "text": finding.text,
        "question": finding.question,
        "locator": finding.locator,
        "span": finding.span,
        "call_id": finding.call_id,
    }


def _finding_from_dict(data: dict[str, Any]) -> Finding:
    """Read one finding back."""
    return Finding(
        text=str(data.get("text", "")),
        question=str(data.get("question", "")),
        locator=str(data.get("locator", "")),
        span=str(data.get("span", "")),
        call_id=str(data.get("call_id", "")),
    )


def _enum(kind: Any, value: Any, fallback: Any) -> Any:
    """Read an enum member by value, falling back on anything else."""
    try:
        return kind(value)
    except ValueError:
        return fallback


def _dicts(value: Any) -> list[dict[str, Any]]:
    """Take the dict members out of a payload's list."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _strings(value: Any) -> list[str]:
    """Take the string members out of a payload's list."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _optional_str(value: Any) -> str | None:
    """Keep a string, or None for anything else."""
    return value if isinstance(value, str) else None


def _optional_int(value: Any) -> int | None:
    """Keep an int, or None for anything else."""
    return int(value) if isinstance(value, int) else None


def _optional_float(value: Any) -> float | None:
    """Keep a number as a float, or None for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
