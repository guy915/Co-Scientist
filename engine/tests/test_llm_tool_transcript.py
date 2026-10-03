"""Offline contracts for llm tool transcript."""

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


def _result(payload: Any) -> dict[str, Any]:
    """Builds one tool-result message carrying a JSON payload."""
    return {
        "role": "tool",
        "tool_call_id": "c1",
        "content": json.dumps(payload),
    }


def _llm_tool_transcript_papers_paper(
    pmid: str, abstract: str = "A long abstract."
) -> dict[str, Any]:
    """Builds one paper record as a search tool returns it."""
    return {"source_id": pmid, "title": f"Paper {pmid}", "abstract": abstract}


def test_a_repeat_keeps_its_identity_and_loses_its_body() -> None:
    """The second copy stays citable and stops costing tokens.

    Measured on a live drafting pass: 8 searches returned 94 records
    carrying 61 distinct papers, so 35% were abstracts the transcript
    already held -- in a loop where literature results are 96% of the
    transcript, and where the token ceiling rather than the turn count
    is what stops it.
    """
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
    # Identity survives, so a citation still resolves.
    assert repeat["title"] == "Paper 222"
    assert "abstract" not in repeat
    assert "re-fetch" in repeat["elided"]
    assert fresh["abstract"] == "A long abstract."


def test_the_first_copy_is_left_whole() -> None:
    """Eliding the original would delete the evidence, not a duplicate."""
    messages = [
        _result({"results": [_llm_tool_transcript_papers_paper("111")]})
    ]

    assert elide_repeated_papers(messages) == 0
    assert json.loads(messages[0]["content"])["results"][0]["abstract"] == (
        "A long abstract."
    )


def test_a_dict_keyed_payload_is_handled_too() -> None:
    """PubMed returns records keyed by id, not as a list.

    Recognising a paper by its own fields rather than by the envelope
    around it is what makes this cover a source added later without
    anyone remembering to update it.
    """
    messages = [
        _result({"111": _llm_tool_transcript_papers_paper("111")}),
        _result({"records": [_llm_tool_transcript_papers_paper("111")]}),
    ]

    assert elide_repeated_papers(messages) == 1


def test_non_paper_tool_results_are_untouched() -> None:
    """A command's output is not a paper and must not be rewritten."""
    messages = [
        _result({"exit_code": 0, "stdout": "done"}),
        _result({"exit_code": 0, "stdout": "done"}),
    ]

    assert elide_repeated_papers(messages) == 0
    assert json.loads(messages[1]["content"])["stdout"] == "done"


def test_an_unparseable_result_is_skipped_not_dropped() -> None:
    """Plain-text tool output stays exactly as the tool produced it."""
    messages = [{"role": "tool", "tool_call_id": "c1", "content": "not json"}]

    assert elide_repeated_papers(messages) == 0
    assert messages[0]["content"] == "not json"


# --- call_llm_with_tools ---------------------------------------------------


def _recording_tool_executor() -> tuple[list[Any], Any]:
    """A tool executor recording its calls, returning a fixed tool result."""
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
    """Assert the threaded history for the executor-then-finish loop."""
    # History: user -> assistant(tool request) -> tool result -> assistant.
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
    """The tool loop executes a requested tool, then ends on a tool-free reply.

    First completion carries a ``tool_calls`` entry, so ``tool_executor`` runs;
    the second completion has ``tool_calls=None`` (falsy), ending the loop and
    returning the final text. Asserts the executor was invoked with the tool
    call, the final text, and that the history threads through user message,
    assistant tool request, tool result, and final assistant message.
    """
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
    # The executor ran exactly once, on the tool call the model requested.
    assert len(seen) == 1
    assert seen[0].id == "call-1"
    assert seen[0].function.name == "search"
    _assert_executor_history(history)


async def test_call_llm_with_tools_no_tool_calls_returns_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A first reply without tool calls returns at once without the executor."""
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
    """A fake ``acompletion`` that records its kwargs into ``captured``."""

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
    """The tool loop's turn carries the same provider handling as call_llm.

    The thinking knob and the reasoning tier come from the shared helpers
    in ``llm.request.completion`` rather than being rebuilt here, and every turn
    asks the provider client to give up on its own via the ``timeout`` argument.
    """
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
    """Run one tool-free loop turn and return the kwargs litellm received."""
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
    """A thinking tool-loop turn never goes out on an answer-sized budget.

    Every turn here reasons, and ``max_tokens`` bounds the chain of thought
    as well as the answer, so an answer-sized budget lets the reasoning
    consume the whole allowance: empty content, billed in full, retried. The
    budgets that reach this path make that reachable rather than theoretical
    -- the draft agent's scaled budget is under the floor at every count a
    run tier asks for, and validation synthesis starts under it too.

    Asserted at the litellm seam rather than on the arg builder, because the
    defect being pinned was the tool loop restating ``call_llm``'s thinking
    knobs instead of sharing the helper that also carries this floor.
    """
    from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS

    captured = await _captured_tool_loop_args(
        monkeypatch, "deepseek/deepseek-v4-flash", 4000
    )

    assert captured["max_tokens"] == THINKING_FLOOR_MAX_TOKENS


async def test_tool_loop_token_floor_never_lowers_a_larger_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The floor only raises: a call site sized above it keeps its own."""
    from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS

    above_floor = THINKING_FLOOR_MAX_TOKENS + 6000
    captured = await _captured_tool_loop_args(
        monkeypatch, "deepseek/deepseek-v4-pro", above_floor
    )

    assert captured["max_tokens"] == above_floor


async def test_tool_loop_token_floor_not_applied_to_non_thinking_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model without a thinking mode spends its budget on the answer.

    It is also sent no ``extra_body`` at all, matching ``call_llm``: the
    restated version set the key to an empty dict for every non-thinking
    provider, which is the tell that the two paths were shaping thinking
    independently rather than sharing one helper.
    """
    captured = await _captured_tool_loop_args(
        monkeypatch, "gemini/gemini-2.5-flash", 4000
    )

    assert captured["max_tokens"] == 4000
    assert "extra_body" not in captured


def test_message_to_history_preserves_reasoning_content() -> None:
    """Thinking's reasoning_content is echoed back on a tool-call turn.

    DeepSeek rejects a follow-up turn whose assistant tool-call message drops
    the reasoning_content it emitted, so the replayed history must keep it.
    """
    from co_scientist.llm.tools.transcript import _message_to_history_dict

    message = _message(
        "", tool_calls=[_tool_call("call-1", "search", '{"q": 1}')]
    )
    message.reasoning_content = "chain of thought"

    result = _message_to_history_dict(message)

    assert result["reasoning_content"] == "chain of thought"
    assert result["tool_calls"][0]["id"] == "call-1"


def test_message_to_history_omits_absent_reasoning_content() -> None:
    """A non-thinking message carries no reasoning_content key."""
    from co_scientist.llm.tools.transcript import _message_to_history_dict

    result = _message_to_history_dict(_message("final answer"))

    assert "reasoning_content" not in result
    assert result["content"] == "final answer"


# --- ToolLoop.tool_contract: cache invalidation (I4) -----------------------


async def _run_tool_loop_no_tools(
    prompt: str, tool_contract: dict[str, Any] | None
) -> str:
    """Run one no-tool-call ``call_llm_with_tools`` iteration, cache live."""

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
    """A changed ``tool_contract`` misses a prior cached transcript.

    Same prompt and tool *schema* both times -- only the resolved tool
    configuration behind that schema differs -- so a cache keyed on prompt
    and schema alone would wrongly replay the first call's answer.
    """
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
    """Two identical calls share one cache entry.

    Same prompt, tools, and tool_contract -- the second is served from
    cache, not re-completed.
    """
    cache_obj = LLMCache(cache_dir=str(tmp_path), enabled=True)
    monkeypatch.setattr(precall, "get_cache", lambda: cache_obj)
    state = _patch_acompletion(monkeypatch, [_completion(_message("answer"))])
    contract = {"pubmed": {"enabled": True}}

    first = await _run_tool_loop_no_tools("same prompt", contract)
    second = await _run_tool_loop_no_tools("same prompt", contract)

    assert first == second == "answer"
    assert state["calls"] == 1
