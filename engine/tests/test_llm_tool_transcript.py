from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.cache import LLMCache
from co_scientist.llm import (
    CompletionSpec,
    ToolLoop,
    call_llm_with_tools,
    precall,
)
from co_scientist.llm.tools.loop import _drop_dead_context
from co_scientist.llm.tools.transcript import _ELIDED_NOTE as _NOTE
from co_scientist.llm.tools.transcript import (
    elide_aged_evidence,
    elide_repeated_papers,
)
from tests._llm_fake import SEARCH_TOOL as _SEARCH_TOOL
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_fake import install_fake_backend
from tests._llm_fake import make_completion as _completion
from tests._llm_fake import make_message as _message
from tests._llm_fake import make_tool_call as _tool_call
from tests._llm_fake import patch_acompletion as _patch_acompletion

_ABSTRACT = "A long abstract."


def _llm_tool_transcript_aging_paper(pmid: str) -> dict[str, Any]:
    return {"source_id": pmid, "title": f"Paper {pmid}", "abstract": _ABSTRACT}


def _turn(*pmids: str) -> list[dict[str, Any]]:
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
            "content": json.dumps(
                {
                    "results": [
                        _llm_tool_transcript_aging_paper(p) for p in pmids
                    ]
                }
            ),
        },
    ]


def _records(message: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = json.loads(message["content"])["results"]
    return records


def _abstracts(message: dict[str, Any]) -> dict[str, str]:
    return {
        record["source_id"]: record["abstract"]
        for record in _records(message)
        if "abstract" in record
    }


def test_a_search_outside_the_window_loses_its_bodies() -> None:
    """Tool turns rebuy the whole transcript, including abstracts no longer
    needed."""
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
    messages = [{"role": "user", "content": "goal"}, *_turn("111")]

    assert elide_aged_evidence(messages) == 0
    assert _abstracts(messages[2]) == {"111": _ABSTRACT}


def test_ageing_the_same_transcript_twice_changes_nothing() -> None:
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
    """Ageing must precede dedup or a stale note can cause deletion of the
    only fresh body."""
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
    page = "p" * 9000
    messages = [
        {"role": "user", "content": "goal"},
        *_turn("111"),
        *_fetch_turn("u1", "read_url", page),
    ]

    assert elide_aged_evidence(messages) == 0
    assert page in messages[4]["content"]


def test_an_aged_search_result_is_not_blanked_wholesale() -> None:
    messages = [
        {"role": "user", "content": "goal"},
        *_turn("111"),
        *_turn("222"),
        *_turn("333"),
    ]
    messages[2]["name"] = "search_pubmed"

    elide_aged_evidence(messages)

    assert _records(messages[2])[0]["title"] == "Paper 111"


def _result(payload: Any) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": "c1",
        "content": json.dumps(payload),
    }


def _llm_tool_transcript_papers_paper(
    pmid: str, abstract: str = "A long abstract."
) -> dict[str, Any]:
    return {"source_id": pmid, "title": f"Paper {pmid}", "abstract": abstract}


def test_a_repeat_keeps_its_identity_and_loses_its_body() -> None:
    """Duplicate abstracts are rebilled by every subsequent turn without
    adding evidence."""
    messages = [
        _result(
            {
                "results": [
                    _llm_tool_transcript_papers_paper("111"),
                    _llm_tool_transcript_papers_paper("222"),
                ]
            }
        ),
        _result(
            {
                "results": [
                    _llm_tool_transcript_papers_paper("222"),
                    _llm_tool_transcript_papers_paper("333"),
                ]
            }
        ),
    ]

    elided = elide_repeated_papers(messages)

    assert elided == 1
    second = json.loads(messages[1]["content"])["results"]
    repeat = next(p for p in second if p["source_id"] == "222")
    fresh = next(p for p in second if p["source_id"] == "333")
    assert repeat["title"] == "Paper 222"
    assert "abstract" not in repeat
    assert "re-fetch" in repeat["elided"]
    assert fresh["abstract"] == "A long abstract."


def test_the_first_copy_is_left_whole() -> None:
    messages = [
        _result({"results": [_llm_tool_transcript_papers_paper("111")]})
    ]

    assert elide_repeated_papers(messages) == 0
    assert json.loads(messages[0]["content"])["results"][0]["abstract"] == (
        "A long abstract."
    )


def test_a_dict_keyed_payload_is_handled_too() -> None:
    """Sources return different envelopes; paper identity must come from
    record fields."""
    messages = [
        _result({"111": _llm_tool_transcript_papers_paper("111")}),
        _result({"records": [_llm_tool_transcript_papers_paper("111")]}),
    ]

    assert elide_repeated_papers(messages) == 1


def test_non_paper_tool_results_are_untouched() -> None:
    messages = [
        _result({"exit_code": 0, "stdout": "done"}),
        _result({"exit_code": 0, "stdout": "done"}),
    ]

    assert elide_repeated_papers(messages) == 0
    assert json.loads(messages[1]["content"])["stdout"] == "done"


def test_an_unparseable_result_is_skipped_not_dropped() -> None:
    messages = [{"role": "tool", "tool_call_id": "c1", "content": "not json"}]

    assert elide_repeated_papers(messages) == 0
    assert messages[0]["content"] == "not json"


def _recording_tool_executor() -> tuple[list[Any], Any]:
    seen: list[Any] = []

    async def tool_executor(tc: Any) -> dict[str, Any]:
        seen.append(tc)
        return {
            "role": "tool",
            "tool_call_id": tc.id,
            "content": "tool result",
        }

    return seen, tool_executor


def _assert_executor_history(history: list[dict[str, Any]]) -> None:
    assert history[0] == {"role": "user", "content": "a prompt"}
    assert history[1]["tool_calls"][0]["id"] == "call-1"
    assert history[2] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "tool result",
    }
    assert history[-1]["content"] == "final answer"


async def test_call_llm_with_tools_runs_executor_then_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    first = _completion(
        _message(None, tool_calls=[_tool_call("call-1", "search", '{"q": 1}')])
    )
    second = _completion(_message("final answer"))
    state = _patch_acompletion(monkeypatch, [first, second])

    seen, tool_executor = _recording_tool_executor()

    final_text, history = await call_llm_with_tools(
        "a prompt",
        CompletionSpec(model_name="test-model"),
        ToolLoop(tools=_SEARCH_TOOL, executor=tool_executor),
    )

    assert final_text == "final answer"
    assert state["calls"] == 2
    assert len(seen) == 1
    assert seen[0].id == "call-1"
    assert seen[0].function.name == "search"
    _assert_executor_history(history)


async def test_call_llm_with_tools_no_tool_calls_returns_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("direct answer"))])

    called = {"ran": False}

    async def tool_executor(_tc: Any) -> dict[str, Any]:
        called["ran"] = True
        return {"role": "tool", "content": ""}

    final_text, history = await call_llm_with_tools(
        "a prompt",
        CompletionSpec(model_name="test-model"),
        ToolLoop(tools=_SEARCH_TOOL, executor=tool_executor),
    )

    assert final_text == "direct answer"
    assert called["ran"] is False
    assert history[-1]["content"] == "direct answer"


def _capturing_acompletion(captured: dict[str, Any]) -> Any:

    async def acompletion(**kwargs: Any) -> SimpleNamespace:
        captured.clear()
        captured.update(kwargs)
        return _completion(_message("direct answer"))

    return acompletion


async def _raising_tool_executor(_tc: Any) -> dict[str, Any]:
    raise AssertionError("no tool call should run")


async def test_tool_loop_applies_provider_quirks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_cache(monkeypatch)
    captured: dict[str, Any] = {}
    install_fake_backend(monkeypatch, _capturing_acompletion(captured))

    await call_llm_with_tools(
        "a prompt",
        CompletionSpec(model_name="deepseek/deepseek-v4-pro"),
        ToolLoop(tools=_SEARCH_TOOL, executor=_raising_tool_executor),
    )
    assert captured["extra_body"] == {"thinking": {"type": "enabled"}}
    assert captured["reasoning_effort"] == "high"
    assert captured["timeout"] > 0

    await call_llm_with_tools(
        "a prompt",
        CompletionSpec(model_name="deepseek/deepseek-v4-pro"),
        ToolLoop(tools=_SEARCH_TOOL, executor=_raising_tool_executor),
    )
    assert captured["reasoning_effort"] == "high"


async def _captured_tool_loop_args(
    monkeypatch: pytest.MonkeyPatch, model_name: str, max_tokens: int
) -> dict[str, Any]:
    _disable_cache(monkeypatch)
    captured: dict[str, Any] = {}
    install_fake_backend(monkeypatch, _capturing_acompletion(captured))

    await call_llm_with_tools(
        "a prompt",
        CompletionSpec(model_name=model_name, max_tokens=max_tokens),
        ToolLoop(tools=_SEARCH_TOOL, executor=_raising_tool_executor),
    )
    return captured


async def test_tool_loop_turn_raised_to_the_token_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS

    captured = await _captured_tool_loop_args(
        monkeypatch, "deepseek/deepseek-v4-flash", 4000
    )

    assert captured["max_tokens"] == THINKING_FLOOR_MAX_TOKENS


async def test_tool_loop_token_floor_never_lowers_a_larger_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS

    above_floor = THINKING_FLOOR_MAX_TOKENS + 6000
    captured = await _captured_tool_loop_args(
        monkeypatch, "deepseek/deepseek-v4-pro", above_floor
    )

    assert captured["max_tokens"] == above_floor


async def test_tool_loop_token_floor_not_applied_to_non_thinking_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = await _captured_tool_loop_args(
        monkeypatch, "gemini/gemini-2.5-flash", 4000
    )

    assert captured["max_tokens"] == 4000
    assert "extra_body" not in captured


def test_message_to_history_preserves_reasoning_content() -> None:
    """DeepSeek rejects follow-up tool turns missing the prior
    reasoning_content."""
    from co_scientist.llm.tools.transcript import _message_to_history_dict

    message = _message(
        "", tool_calls=[_tool_call("call-1", "search", '{"q": 1}')]
    )
    message.reasoning_content = "chain of thought"

    result = _message_to_history_dict(message)

    assert result["reasoning_content"] == "chain of thought"
    assert result["tool_calls"][0]["id"] == "call-1"


def test_message_to_history_omits_absent_reasoning_content() -> None:
    """DeepSeek rejects follow-up tool turns missing the prior
    reasoning_content."""
    from co_scientist.llm.tools.transcript import _message_to_history_dict

    result = _message_to_history_dict(_message("final answer"))

    assert "reasoning_content" not in result
    assert result["content"] == "final answer"


async def _run_tool_loop_no_tools(
    prompt: str, tool_contract: dict[str, Any] | None
) -> str:

    async def tool_executor(_tc: Any) -> dict[str, Any]:
        raise AssertionError("no tool call should run")

    final_text, _ = await call_llm_with_tools(
        prompt,
        CompletionSpec(model_name="test-model"),
        ToolLoop(
            tools=_SEARCH_TOOL,
            executor=tool_executor,
            tool_contract=tool_contract,
        ),
    )
    return final_text


async def test_tool_contract_change_is_a_cache_miss(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Equal schemas can hide changed tool configuration; cached transcripts
    need that contract."""
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    monkeypatch.setattr(precall, "get_cache", lambda: cache_obj)
    state = _patch_acompletion(
        monkeypatch,
        [
            _completion(_message("answer one")),
            _completion(_message("answer two")),
        ],
    )

    first = await _run_tool_loop_no_tools(
        "same prompt", {"pubmed": {"enabled": True}}
    )
    second = await _run_tool_loop_no_tools(
        "same prompt", {"pubmed": {"enabled": False}}
    )

    assert first == "answer one"
    assert second == "answer two"
    assert state["calls"] == 2


async def test_identical_tool_contract_is_a_cache_hit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    monkeypatch.setattr(precall, "get_cache", lambda: cache_obj)
    state = _patch_acompletion(monkeypatch, [_completion(_message("answer"))])
    contract = {"pubmed": {"enabled": True}}

    first = await _run_tool_loop_no_tools("same prompt", contract)
    second = await _run_tool_loop_no_tools("same prompt", contract)

    assert first == second == "answer"
    assert state["calls"] == 1
