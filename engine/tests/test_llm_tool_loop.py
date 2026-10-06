from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.llm import CompletionSpec, ToolLoop, call_llm_with_tools
from co_scientist.llm.tools.loop import _drop_dead_context
from co_scientist.llm.tools.policy import _turns_remaining
from co_scientist.llm.tools.transcript import (
    ABORTED_RESULT,
    elide_aged_evidence,
    elide_superseded_writes,
    normalize_tool_transcript,
)
from tests._llm_fake import (
    SEARCH_TOOL,
    disable_llm_cache,
    echo_executor,
    make_completion,
    make_message,
    make_tool_call,
    patch_acompletion,
)

_SPEC = CompletionSpec(model_name="test/model", max_tokens=100)


def _asks_for_a_tool(call_id: str = "call-0") -> SimpleNamespace:
    return make_completion(
        make_message(None, tool_calls=[make_tool_call(call_id, "search", "{}")])
    )


def _loop(max_iterations: int, **overrides: Any) -> ToolLoop:
    return ToolLoop(
        tools=SEARCH_TOOL,
        executor=echo_executor,
        max_iterations=max_iterations,
        **overrides,
    )


@pytest.mark.parametrize(
    ("max_iterations", "tool_turns", "handoffs"),
    [(5, 4, 1), (3, 1, 0)],
    ids=["warned-before-the-cap", "too-short-to-warn"],
)
async def test_the_model_is_warned_once_before_its_turns_run_out(
    monkeypatch: pytest.MonkeyPatch,
    max_iterations: int,
    tool_turns: int,
    handoffs: int,
) -> None:
    disable_llm_cache(monkeypatch)
    patch_acompletion(
        monkeypatch,
        [_asks_for_a_tool(f"call-{i}") for i in range(tool_turns)]
        + [make_completion(make_message("final answer"))],
    )

    final, history = await call_llm_with_tools(
        "a prompt", _SPEC, _loop(max_iterations)
    )

    assert final == "final answer"
    warnings = [
        m
        for m in history
        if m.get("role") == "user"
        and "tool-calling turn(s) left" in str(m.get("content", ""))
    ]
    assert len(warnings) == handoffs
    if handoffs:
        assert "1 tool-calling turn(s) left" in warnings[0]["content"]


async def test_a_loop_stops_on_spend_before_it_runs_out_of_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Growing transcripts make turn counts insufficient to bound token
    spend."""
    disable_llm_cache(monkeypatch)
    fat = "x" * 40_000
    patch_acompletion(
        monkeypatch,
        [
            make_completion(
                make_message(
                    fat,
                    tool_calls=[make_tool_call(f"call-{i}", "search", "{}")],
                )
            )
            for i in range(50)
        ],
    )

    final, history = await call_llm_with_tools(
        "a prompt", _SPEC, _loop(50, max_prompt_tokens=60_000)
    )

    assert len([m for m in history if m.get("role") == "assistant"]) < 10
    assert final == fat


def test_the_wrap_up_promises_only_the_turns_the_budget_affords() -> None:
    """Advertised turns must fit the remaining spend or the model starts
    unaffordable work."""
    loop = _loop(24, max_prompt_tokens=150_000)
    messages = [{"role": "user", "content": "x" * 40_000}]

    assert _turns_remaining(13, 120_000, loop, messages) == 3
    assert _turns_remaining(13, 150_000, loop, messages) == 1


async def test_running_out_of_turns_gets_one_tool_free_closing_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paid-for work must survive a ceiling, and keeping tools would let the
    model spend the closing turn on another unaffordable action."""
    disable_llm_cache(monkeypatch)
    sent: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch,
        [
            *[_asks_for_a_tool(f"call-{i}") for i in range(4)],
            make_completion(make_message("what I got as far as")),
        ],
        recorder=sent,
    )

    final, _ = await call_llm_with_tools("a prompt", _SPEC, _loop(4))

    assert final == "what I got as far as"
    assert all("tools" in request for request in sent[:-1])
    assert "tools" not in sent[-1]
    closing = str(sent[-1]["messages"][-1]["content"])
    assert "final turn" in closing
    assert "do not propose further steps" in closing.lower()


async def test_a_closing_turn_that_answers_nothing_still_fails_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed closing turn must not weaken the hard spend ceiling."""
    disable_llm_cache(monkeypatch)
    patch_acompletion(
        monkeypatch,
        [
            *[_asks_for_a_tool(f"call-{i}") for i in range(5)],
            make_completion(make_message("")),
        ],
    )

    with pytest.raises(RuntimeError, match="exhausted its budget"):
        await call_llm_with_tools("a prompt", _SPEC, _loop(5))


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


async def test_a_truncated_tool_call_is_answered_with_an_error_not_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disable_llm_cache(monkeypatch)
    truncated = make_completion(
        make_message(
            None,
            tool_calls=[make_tool_call("call-1", "search", '{"q": "unfinish')],
        )
    )
    requests: list[dict[str, Any]] = []
    patch_acompletion(
        monkeypatch,
        [truncated, make_completion(make_message("final"))],
        requests,
    )
    seen: list[Any] = []

    async def executor(tc: Any) -> dict[str, Any]:
        seen.append(tc)
        return {"role": "tool", "tool_call_id": tc.id, "content": "result"}

    text, _ = await call_llm_with_tools(
        "a prompt", _SPEC, ToolLoop(tools=SEARCH_TOOL, executor=executor)
    )

    assert text == "final"
    assert seen == []
    resent = requests[1]["messages"]
    assert resent[1]["tool_calls"][0]["function"]["arguments"] == "{}"
    assert resent[2]["tool_call_id"] == "call-1"
    assert "Re-issue the call" in resent[2]["content"]
