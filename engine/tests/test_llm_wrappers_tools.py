"""Tests for the ``call_llm_with_tools`` tool loop.

Split from ``test_llm_wrappers.py``: covers the loop that executes model-
requested tool calls, the message history it threads through, the provider
handling each loop turn carries, and ``_message_to_history_dict``. The
litellm boundary is faked exactly as described in
``tests/_llm_wrapper_fakes.py``; caching is disabled per test via
``tests._llm_fake.disable_llm_cache``.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.llm import (
    CompletionSpec,
    ToolLoop,
    call_llm_with_tools,
)
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests._llm_wrapper_fakes import (
    SEARCH_TOOL as _SEARCH_TOOL,
)
from tests._llm_wrapper_fakes import (
    make_completion as _completion,
)
from tests._llm_wrapper_fakes import (
    make_message as _message,
)
from tests._llm_wrapper_fakes import (
    make_tool_call as _tool_call,
)
from tests._llm_wrapper_fakes import (
    patch_acompletion as _patch_acompletion,
)

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

    DashScope's compatible-mode endpoint does not support
    ``reasoning_effort`` (the guard lives in
    ``llm_request.reasoning_effort_args``), and every turn asks the
    provider client to give up on its own via the ``timeout`` argument.
    """
    _disable_cache(monkeypatch)
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "co_scientist.llm.litellm.acompletion",
        _capturing_acompletion(captured),
    )

    await call_llm_with_tools(
        "a prompt",
        CompletionSpec(model_name="dashscope/deepseek-v4-pro"),
        ToolLoop(tools=_SEARCH_TOOL, executor=_raising_tool_executor),
    )
    assert captured["extra_body"] == {"enable_thinking": True}
    assert "reasoning_effort" not in captured
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
    monkeypatch.setattr(
        "co_scientist.llm.litellm.acompletion",
        _capturing_acompletion(captured),
    )

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
    -- the draft agent's is capped below the floor outright
    (``DRAFT_MAX_TOKENS_CAP``), and validation synthesis starts under it.

    Asserted at the litellm seam rather than on the arg builder, because the
    defect being pinned was the tool loop restating ``call_llm``'s thinking
    knobs instead of sharing the helper that also carries this floor.
    """
    from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS

    captured = await _captured_tool_loop_args(
        monkeypatch, "dashscope/deepseek-v4-flash", 4000
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
    from co_scientist.llm_tool_loop import _message_to_history_dict

    message = _message(
        "", tool_calls=[_tool_call("call-1", "search", '{"q": 1}')]
    )
    message.reasoning_content = "chain of thought"

    result = _message_to_history_dict(message)

    assert result["reasoning_content"] == "chain of thought"
    assert result["tool_calls"][0]["id"] == "call-1"


def test_message_to_history_omits_absent_reasoning_content() -> None:
    """A non-thinking message carries no reasoning_content key."""
    from co_scientist.llm_tool_loop import _message_to_history_dict

    result = _message_to_history_dict(_message("final answer"))

    assert "reasoning_content" not in result
    assert result["content"] == "final answer"
