"""Evidence the model has already read stops being re-sent forever."""

from __future__ import annotations

import json
from typing import Any

from co_scientist.llm_tool_loop import _drop_dead_context
from co_scientist.llm_tool_transcript import (
    _ELIDED_NOTE as _NOTE,
)
from co_scientist.llm_tool_transcript import elide_aged_evidence

_ABSTRACT = "A long abstract."


def _paper(pmid: str) -> dict[str, Any]:
    """Builds one paper record as a search tool returns it."""
    return {"source_id": pmid, "title": f"Paper {pmid}", "abstract": _ABSTRACT}


def _turn(*pmids: str) -> list[dict[str, Any]]:
    """Builds one assistant search turn and the result answering it."""
    call_id = f"c{'-'.join(pmids)}"
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "search_pubmed", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps({"results": [_paper(p) for p in pmids]}),
        },
    ]


def _records(message: dict[str, Any]) -> list[dict[str, Any]]:
    """The records one tool result now carries."""
    records: list[dict[str, Any]] = json.loads(message["content"])["results"]
    return records


def _abstracts(message: dict[str, Any]) -> dict[str, str]:
    """The abstract each record in one tool result still carries."""
    return {
        record["source_id"]: record["abstract"]
        for record in _records(message)
        if "abstract" in record
    }


def test_a_search_outside_the_window_loses_its_bodies() -> None:
    """The loop stops paying for abstracts it read many turns ago.

    A tool loop re-sends its whole transcript every turn, so an abstract
    that arrived on turn two is billed again by every turn after it. The
    drafting loop ran out of room this way rather than finishing.
    """
    messages = [
        {"role": "user", "content": "goal"},
        *_turn("111"),
        *_turn("222"),
        *_turn("333"),
    ]

    elided = elide_aged_evidence(messages)

    assert elided == 1
    assert _records(messages[2])[0]["elided"] == _NOTE
    assert "abstract" not in _records(messages[2])[0]


def test_the_most_recent_searches_are_left_whole() -> None:
    """A record has to arrive in full and stay long enough to be used."""
    messages = [
        {"role": "user", "content": "goal"},
        *_turn("111"),
        *_turn("222"),
        *_turn("333"),
    ]

    elide_aged_evidence(messages)

    assert _abstracts(messages[4]) == {"222": _ABSTRACT}
    assert _abstracts(messages[6]) == {"333": _ABSTRACT}


def test_an_aged_record_keeps_what_makes_it_citable() -> None:
    """Losing the title too would cost the draft its source list."""
    messages = [
        {"role": "user", "content": "goal"},
        *_turn("111"),
        *_turn("222"),
        *_turn("333"),
    ]

    elide_aged_evidence(messages)

    aged = _records(messages[2])[0]
    assert aged["title"] == "Paper 111"
    assert aged["source_id"] == "111"
    assert "re-fetch" in aged["elided"]


def test_a_short_conversation_is_left_alone() -> None:
    """Nothing ages out before the window it is measured against fills."""
    messages = [{"role": "user", "content": "goal"}, *_turn("111")]

    assert elide_aged_evidence(messages) == 0
    assert _abstracts(messages[2]) == {"111": _ABSTRACT}


def test_ageing_the_same_transcript_twice_changes_nothing() -> None:
    """It runs at the top of every turn, so it must not compound."""
    messages = [
        {"role": "user", "content": "goal"},
        *_turn("111"),
        *_turn("222"),
        *_turn("333"),
    ]

    elide_aged_evidence(messages)
    before = messages[2]["content"]

    assert elide_aged_evidence(messages) == 0
    assert messages[2]["content"] == before


def test_a_record_found_again_after_ageing_out_keeps_its_new_copy() -> None:
    """The two eliders must not between them delete every copy.

    An aged record's body field holds a note, which is as truthy as an
    abstract. Read naively, the duplicate pass registers that dead copy
    as the original and elides the *fresh* one that replaced it -- and
    the transcript ends up holding no text and two notes, each pointing
    at the other. The model can no longer read a paper it just searched
    for and has nothing saying so.
    """
    messages = [
        {"role": "user", "content": "goal"},
        *_turn("111"),
        *_turn("222"),
        *_turn("333"),
        *_turn("111"),
    ]

    _drop_dead_context(messages)
    _drop_dead_context(messages)

    assert _abstracts(messages[8]) == {"111": _ABSTRACT}


def test_non_paper_results_are_untouched() -> None:
    """A command's output is not evidence anyone can re-fetch."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": "goal"}]
    for index in range(3):
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"r{index}",
                        "type": "function",
                        "function": {"name": "run_command", "arguments": "{}"},
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": f"r{index}",
                "content": json.dumps({"exit_code": 0, "stdout": "done"}),
            }
        )

    assert elide_aged_evidence(messages) == 0
    assert json.loads(messages[2]["content"])["stdout"] == "done"


def _fetch_turn(call_id: str, tool: str, text: str) -> list[dict[str, Any]]:
    """Builds one assistant fetch turn and the document it returned."""
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": tool, "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "name": tool,
            "tool_call_id": call_id,
            "content": json.dumps(text),
        },
    ]


def test_an_aged_page_loses_its_text() -> None:
    """A fetched page is the other half of the transcript's dead weight.

    Measured on a live drafting pass: four `read_url` calls left 43k
    characters in the transcript, ~24% of everything that pass re-sent,
    and unlike a search result there is nothing inside it to keep.
    """
    page = "p" * 9000
    messages = [
        {"role": "user", "content": "goal"},
        *_fetch_turn("u1", "read_url", page),
        *_turn("222"),
        *_turn("333"),
    ]

    assert elide_aged_evidence(messages) == 1
    assert page not in messages[2]["content"]
    assert "Call the same tool again" in messages[2]["content"]


def test_a_recent_page_is_left_whole() -> None:
    """The model has to be able to read what it just fetched."""
    page = "p" * 9000
    messages = [
        {"role": "user", "content": "goal"},
        *_turn("111"),
        *_fetch_turn("u1", "read_url", page),
    ]

    assert elide_aged_evidence(messages) == 0
    assert page in messages[4]["content"]


def test_an_aged_search_result_is_not_blanked_wholesale() -> None:
    """A search result is records; only a document is replaced entirely."""
    messages = [
        {"role": "user", "content": "goal"},
        *_turn("111"),
        *_turn("222"),
        *_turn("333"),
    ]
    messages[2]["name"] = "search_pubmed"

    elide_aged_evidence(messages)

    assert _records(messages[2])[0]["title"] == "Paper 111"
