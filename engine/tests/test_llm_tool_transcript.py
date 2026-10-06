from __future__ import annotations

import json
from typing import Any

import pytest

from co_scientist.llm.tools.loop import _drop_dead_context
from co_scientist.llm.tools.transcript import (
    ABORTED_RESULT,
    elide_aged_evidence,
    elide_repeated_papers,
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


@pytest.mark.parametrize("named", [False, True])
def test_an_aged_search_loses_its_bodies_but_stays_citable(named: bool) -> None:
    """Tool turns rebuy the whole transcript, including abstracts no longer
    needed."""
    messages = [_GOAL, *_turn("111"), *_turn("222"), *_turn("333")]
    if named:
        messages[2]["name"] = "search_pubmed"

    assert elide_aged_evidence(messages) == 1

    aged = _records(messages[2])[0]
    assert "abstract" not in aged
    assert (aged["source_id"], aged["title"]) == ("111", "Paper 111")
    assert "re-fetch" in aged["elided"]
    assert _records(messages[4])[0]["abstract"] == _ABSTRACT
    assert _records(messages[6])[0]["abstract"] == _ABSTRACT
    before = messages[2]["content"]
    assert elide_aged_evidence(messages) == 0, "ageing twice changes nothing"
    assert messages[2]["content"] == before


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


@pytest.mark.parametrize(
    "messages",
    [
        [_GOAL, *_turn("111")],
        [_GOAL, *_turn("111"), *_fetch_turn("u1", "read_url", "p" * 9000)],
        [
            _GOAL,
            *[
                m
                for i in range(3)
                for m in (
                    _call(f"r{i}", "run_command"),
                    {
                        "role": "tool",
                        "tool_call_id": f"r{i}",
                        "content": json.dumps({"exit_code": 0}),
                    },
                )
            ],
        ],
    ],
    ids=["short-conversation", "recent-page", "non-paper-results"],
)
def test_recent_and_non_paper_results_are_left_whole(
    messages: list[dict[str, Any]],
) -> None:
    before = json.dumps(messages)

    assert elide_aged_evidence(messages) == 0
    assert json.dumps(messages) == before


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


def test_a_repeat_keeps_its_identity_and_loses_its_body() -> None:
    """Duplicate abstracts are rebilled by every subsequent turn without
    adding evidence."""
    messages = [
        _result({"results": [_paper("111"), _paper("222")]}),
        _result({"results": [_paper("222"), _paper("333")]}),
    ]

    assert elide_repeated_papers(messages) == 1

    first, second = (_records(m) for m in messages)
    assert [p["abstract"] for p in first] == [_ABSTRACT] * 2
    repeat, fresh = second
    assert repeat["title"] == "Paper 222"
    assert "abstract" not in repeat
    assert "re-fetch" in repeat["elided"]
    assert fresh["abstract"] == _ABSTRACT


@pytest.mark.parametrize(
    ("messages", "elided"),
    [
        (
            [
                _result({"111": _paper("111")}),
                _result({"records": [_paper("111")]}),
            ],
            1,
        ),
        ([_result({"exit_code": 0}), _result({"exit_code": 0})], 0),
        (
            [{"role": "tool", "tool_call_id": "c1", "content": "not json"}],
            0,
        ),
    ],
    ids=["dict-keyed-envelope", "non-paper-results", "unparseable-result"],
)
def test_paper_identity_comes_from_record_fields_and_odd_results_are_skipped(
    messages: list[dict[str, Any]], elided: int
) -> None:
    assert elide_repeated_papers(messages) == elided


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


def _shape(messages: list[dict[str, Any]]) -> list[str]:
    return [m.get("tool_call_id") or m["role"] for m in messages]


@pytest.mark.parametrize(
    ("messages", "shape"),
    [
        ([_assistant("a"), _answer("a")], ["assistant", "a"]),
        ([_assistant("a")], ["assistant", "a"]),
        ([_assistant("a", "b"), _answer("a")], ["assistant", "b", "a"]),
        (
            [_assistant("a"), {"role": "user", "content": "next"}],
            ["assistant", "a", "user"],
        ),
        ([_GOAL, _answer("ghost")], ["user"]),
    ],
    ids=[
        "complete",
        "unanswered-call",
        "partly-answered",
        "result-sits-beside-its-call",
        "result-answering-no-call",
    ],
)
def test_every_tool_call_is_paired_with_a_result_beside_it(
    messages: list[dict[str, Any]], shape: list[str]
) -> None:
    """Providers require positional call/result pairing."""
    before = json.dumps(messages)

    assert _shape(normalize_tool_transcript(messages)) == shape
    assert json.dumps(messages) == before, "a cached transcript may be shared"


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


@pytest.mark.parametrize(
    "messages",
    [
        [_write("a", "model.py", "keep"), _write("b", "plot.py", "y")],
        [
            _call("a", "apply_patch", "*** patch"),
            _call("b", "apply_patch", "*** patch"),
        ],
        [_GOAL, _assistant("a")],
    ],
    ids=["different-file", "patches", "no-writes"],
)
def test_only_a_later_overwrite_of_the_same_file_supersedes_a_write(
    messages: list[dict[str, Any]],
) -> None:
    before = json.dumps(messages)

    assert elide_superseded_writes(messages) == 0
    assert json.dumps(messages) == before
