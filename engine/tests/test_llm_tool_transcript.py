"""Repairing a tool transcript cut off mid-turn, and pruning a dead one.

The loop appends the assistant's message and then its results, so an
interruption between the two leaves a conversation the provider rejects
outright -- which reads as the model failing rather than as the
transcript being rebuilt wrong.
"""

from __future__ import annotations

import json
from typing import Any

from co_scientist.llm_tool_transcript import (
    ABORTED_RESULT,
    elide_superseded_writes,
    normalize_tool_transcript,
)


def _assistant(*ids: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "run_command", "arguments": "{}"},
            }
            for call_id in ids
        ],
    }


def _result(call_id: str) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": "run_command",
        "content": "{}",
    }


def _pairs_up(messages: list[dict[str, Any]]) -> bool:
    """Whether every call has a result and every result has a call."""
    requested = {
        call["id"] for m in messages for call in m.get("tool_calls") or ()
    }
    answered = {m["tool_call_id"] for m in messages if m.get("role") == "tool"}
    return requested == answered


def test_a_complete_turn_is_left_alone() -> None:
    messages = [_assistant("a"), _result("a")]
    assert normalize_tool_transcript(messages) == messages


def test_a_call_with_no_result_gets_an_aborted_one() -> None:
    # The state an interrupted turn leaves, and the one the provider
    # refuses to accept at all.
    repaired = normalize_tool_transcript([_assistant("a")])
    assert _pairs_up(repaired)
    assert json.loads(repaired[1]["content"]) == ABORTED_RESULT


def test_only_the_missing_results_are_synthesized() -> None:
    repaired = normalize_tool_transcript([_assistant("a", "b"), _result("a")])
    assert _pairs_up(repaired)
    assert [m.get("tool_call_id") for m in repaired[1:]] == ["b", "a"]


def test_the_synthesized_result_sits_beside_its_call() -> None:
    # Providers check the pairing positionally as well as by id, so a
    # repair appended at the end is still a rejected conversation.
    repaired = normalize_tool_transcript(
        [_assistant("a"), {"role": "user", "content": "next"}]
    )
    assert repaired[1]["tool_call_id"] == "a"
    assert repaired[2]["role"] == "user"


def test_a_result_answering_no_call_is_dropped() -> None:
    # What remains when the assistant message was lost rather than its
    # results; it can be paired with nothing.
    repaired = normalize_tool_transcript(
        [{"role": "user", "content": "go"}, _result("ghost")]
    )
    assert repaired == [{"role": "user", "content": "go"}]


def test_the_request_is_kept_rather_than_the_turn_erased() -> None:
    # Dropping the assistant message would be tidier and worse: the
    # model would be free to ask again forever with no record of why
    # the last attempt produced nothing.
    repaired = normalize_tool_transcript([_assistant("a")])
    assert repaired[0]["tool_calls"][0]["id"] == "a"


def test_the_aborted_result_does_not_claim_nothing_happened() -> None:
    # An aborted run_command may have had every effect it was going to
    # have. A model told it did not run would simply repeat it.
    assert "may have run" in ABORTED_RESULT["detail"]


def test_the_input_list_is_not_modified() -> None:
    # It can be a cached value shared with another caller.
    messages = [_assistant("a")]
    normalize_tool_transcript(messages)
    assert len(messages) == 1


def _write(call_id: str, path: str, content: str) -> dict[str, Any]:
    """An assistant turn writing one file whole."""
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": path, "content": content}),
                },
            }
        ],
    }


def test_an_overwritten_file_stops_being_resent() -> None:
    # The measured cost: one simulation rewrote its model five times and
    # 59% of its transcript was versions of that file that no longer
    # existed, re-sent by every turn after each one.
    messages = [
        _write("a", "model.py", "first" * 400),
        _write("b", "model.py", "second" * 400),
    ]
    assert elide_superseded_writes(messages) == 1
    first = messages[0]["tool_calls"][0]["function"]["arguments"]
    assert "first" not in first
    assert "superseded" in first
    assert "second" in messages[1]["tool_calls"][0]["function"]["arguments"]


def test_the_call_stays_answerable_after_its_text_goes() -> None:
    # Only the arguments go. The id and name stay, because the provider
    # rejects a transcript whose calls and results do not pair up.
    messages = [_write("a", "model.py", "x"), _write("b", "model.py", "y")]
    elide_superseded_writes(messages)
    call = messages[0]["tool_calls"][0]
    assert call["id"] == "a"
    assert call["function"]["name"] == "write_file"
    assert json.loads(call["function"]["arguments"])["path"] == "model.py"


def test_a_different_file_is_not_superseded() -> None:
    messages = [_write("a", "model.py", "keep"), _write("b", "plot.py", "y")]
    assert elide_superseded_writes(messages) == 0
    assert "keep" in messages[0]["tool_calls"][0]["function"]["arguments"]


def test_a_patch_is_left_alone() -> None:
    # A patch is an edit relative to the file it lands on, so an earlier
    # one is not superseded by a later one in any sense worth relying on.
    patch = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "a",
                "function": {"name": "apply_patch", "arguments": "*** patch"},
            }
        ],
    }
    assert elide_superseded_writes([patch, dict(patch)]) == 0


def test_a_loop_with_no_writes_is_untouched() -> None:
    # Every literature loop, which is why this is safe to run on all of
    # them: no write tool is offered, so there is nothing to elide.
    messages = [{"role": "user", "content": "go"}, _assistant("a")]
    before = json.dumps(messages)
    assert elide_superseded_writes(messages) == 0
    assert json.dumps(messages) == before
