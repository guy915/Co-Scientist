from __future__ import annotations

import json
from typing import Any

from co_scientist.llm.tools.loop import _drop_dead_context
from co_scientist.llm.tools.transcript import (
    ABORTED_RESULT,
    elide_aged_evidence,
    elide_superseded_writes,
    normalize_tool_transcript,
)

_ABSTRACT = "A long abstract."
_GOAL = {"role": "user", "content": "goal"}


def _paper(pmid: str) -> dict[str, Any]:
    return {"source_id": pmid, "title": f"Paper {pmid}", "abstract": _ABSTRACT}


def _call(call_id: str, name: str, arguments: str = "{}") -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    }


def _turn(*pmids: str) -> list[dict[str, Any]]:
    call_id = f"c{'-'.join(pmids)}"
    return [
        _call(call_id, "search_pubmed"),
        {
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps({"results": [_paper(p) for p in pmids]}),
        },
    ]


def _fetch_turn(call_id: str, tool: str, text: str) -> list[dict[str, Any]]:
    return [
        _call(call_id, tool),
        {
            "role": "tool",
            "name": tool,
            "tool_call_id": call_id,
            "content": json.dumps(text),
        },
    ]


def _records(message: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = json.loads(message["content"])["results"]
    return records


def _result(payload: Any) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": "c1",
        "content": json.dumps(payload),
    }


def test_an_aged_page_loses_its_text() -> None:
    page = "p" * 9000
    messages = [
        _GOAL,
        *_fetch_turn("u1", "read_url", page),
        *_turn("222"),
        *_turn("333"),
    ]

    assert elide_aged_evidence(messages) == 1
    assert page not in messages[2]["content"]
    assert "Call the same tool again" in messages[2]["content"]


def test_a_record_found_again_after_ageing_out_keeps_its_new_copy() -> None:
    """Ageing must precede dedup or a stale note can cause deletion of the
    only fresh body."""
    messages = [
        _GOAL,
        *_turn("111"),
        *_turn("222"),
        *_turn("333"),
        *_turn("111"),
    ]

    _drop_dead_context(messages)
    _drop_dead_context(messages)

    assert _records(messages[8])[0]["abstract"] == _ABSTRACT


def _assistant(*ids: str) -> dict[str, Any]:
    message = _call(ids[0], "run_command")
    message["tool_calls"] = [
        {**message["tool_calls"][0], "id": call_id} for call_id in ids
    ]
    return message


def _answer(call_id: str) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": "run_command",
        "content": "{}",
    }


def test_a_synthesized_result_does_not_claim_the_command_never_ran() -> None:
    repaired = normalize_tool_transcript([_assistant("a")])

    assert json.loads(repaired[1]["content"]) == ABORTED_RESULT
    assert "may have run" in ABORTED_RESULT["detail"]
    assert repaired[0]["tool_calls"][0]["id"] == "a", "the request is kept"


def _write(call_id: str, path: str, content: str) -> dict[str, Any]:
    return _call(
        call_id,
        "write_file",
        json.dumps({"path": path, "content": content}),
    )


def test_an_overwritten_file_is_dropped_but_its_call_stays_answerable() -> None:
    messages = [
        _write("a", "model.py", "first" * 400),
        _write("b", "model.py", "second" * 400),
    ]

    assert elide_superseded_writes(messages) == 1

    call = messages[0]["tool_calls"][0]
    assert (call["id"], call["function"]["name"]) == ("a", "write_file")
    arguments = call["function"]["arguments"]
    assert "first" not in arguments
    assert "superseded" in arguments
    assert json.loads(arguments)["path"] == "model.py"
    assert "second" in messages[1]["tool_calls"][0]["function"]["arguments"]
