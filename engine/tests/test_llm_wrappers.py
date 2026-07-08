"""Tests for the network-backed LLM wrappers in ``co_scientist.llm``.

These cover ``call_llm``, ``call_llm_json``, and ``call_llm_with_tools`` -- the
three functions that actually reach out to litellm. The single seam each one
shares is ``litellm.acompletion`` (``call_llm_json`` delegates to ``call_llm``
rather than calling litellm itself), so every test monkeypatches
``litellm.acompletion`` with an async fake that returns a litellm-shaped
response object (a ``SimpleNamespace`` tree mirroring
``response.choices[0].message.{role,content,tool_calls}``). No network is
touched.

Caching is disabled deterministically by patching ``co_scientist.llm.get_cache``
to return a fresh ``LLMCache(enabled=False)``: a disabled cache's ``get`` always
returns ``None`` and ``set`` is a no-op, so each call exercises the real
completion path. Patching the env var is unreliable because ``get_cache``
memoizes a process-global instance that may already exist.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist import llm
from co_scientist import prompts as prompts_mod
from co_scientist.cache import LLMCache
from co_scientist.llm import call_llm
from co_scientist.llm import call_llm_json
from co_scientist.llm import call_llm_with_tools

# The real prompt writer, captured at import time -- i.e. before the autouse
# ``_no_prompt_disk_writes`` conftest fixture swaps in its per-test no-op.
_REAL_SAVE_PROMPT_TO_DISK = prompts_mod.save_prompt_to_disk

# --- helpers ---------------------------------------------------------------


def _message(content: str | None,
             tool_calls: list[Any] | None = None,
             role: str = "assistant") -> SimpleNamespace:
    """Build a litellm-shaped ``choices[0].message`` object.

    Args:
        content: The assistant message text (``None`` mirrors an empty
            completion).
        tool_calls: Optional list of tool-call namespaces; ``None`` ends the
            tool loop because the wrapper guards with
            ``and message.tool_calls``.
        role: The message role echoed back into the message history.

    Returns:
        A ``SimpleNamespace`` exposing ``role``, ``content``, and
        ``tool_calls``.
    """
    return SimpleNamespace(role=role, content=content, tool_calls=tool_calls)


def _completion(message: SimpleNamespace) -> SimpleNamespace:
    """Wrap a message in the ``choices[0].message`` envelope litellm returns.

    Args:
        message: The message namespace from :func:`_message`.

    Returns:
        A response namespace with a single choice carrying ``message``.
    """
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _tool_call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    """Build a litellm-shaped tool-call namespace.

    Args:
        call_id: The tool-call id echoed into the message history.
        name: The function name the wrapper reads via ``tc.function.name``.
        arguments: The raw JSON argument string (kept opaque by the wrapper).

    Returns:
        A namespace exposing ``id`` and ``function.{name,arguments}``.
    """
    return SimpleNamespace(id=call_id,
                           function=SimpleNamespace(name=name,
                                                    arguments=arguments))


def _disable_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``llm.get_cache`` to hand back a disabled cache.

    A disabled ``LLMCache`` returns ``None`` from ``get`` and no-ops in ``set``,
    so the completion path always runs and nothing leaks between tests.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    monkeypatch.setattr(llm, "get_cache", lambda: LLMCache(enabled=False))


def _patch_acompletion(monkeypatch: pytest.MonkeyPatch,
                       responses: list[SimpleNamespace]) -> dict[str, int]:
    """Patch ``litellm.acompletion`` to return queued responses in order.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        responses: Completion namespaces to return on successive calls.

    Returns:
        A mutable dict whose ``"calls"`` key counts how many times the fake ran.
    """
    state = {"calls": 0}
    queue = iter(responses)

    async def fake_acompletion(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        state["calls"] += 1
        return next(queue)

    monkeypatch.setattr("co_scientist.llm.litellm.acompletion",
                        fake_acompletion)
    return state


_INT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "a": {
            "type": "integer"
        }
    },
    "required": ["a"],
}


# --- call_llm --------------------------------------------------------------
async def test_call_llm_returns_message_content(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``call_llm`` returns the assistant message content verbatim."""
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("the answer text"))])

    result = await call_llm("a prompt", "test-model")

    assert result == "the answer text"


async def test_call_llm_empty_content_raises(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """``call_llm`` raises ``ValueError`` when the model returns empty content.

    The wrapper treats whitespace-only content as empty (``content.strip()``).
    """
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("   "))])

    with pytest.raises(ValueError, match="None or empty content"):
        await call_llm("a prompt", "test-model")


async def test_call_llm_invoked_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """``call_llm`` makes exactly one completion call on the happy path."""
    _disable_cache(monkeypatch)
    state = _patch_acompletion(monkeypatch, [_completion(_message("hi"))])

    await call_llm("a prompt", "test-model")

    assert state["calls"] == 1


# --- call_llm_json ---------------------------------------------------------


async def test_call_llm_json_parses_clean_object(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Clean JSON content is parsed into a dict and returned."""
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch,
                       [_completion(_message('{"a": 1, "b": "x"}'))])

    result = await call_llm_json("a prompt", "test-model")

    assert result == {"a": 1, "b": "x"}


async def test_call_llm_json_strips_markdown_fence(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A ```json fenced response is unwrapped before parsing.

    Fence stripping lives in ``call_llm_json`` (unlike ``attempt_json_repair``),
    so the inner object is recovered on the first attempt.
    """
    _disable_cache(monkeypatch)
    fenced = '```json\n{"a": 7}\n```'
    _patch_acompletion(monkeypatch, [_completion(_message(fenced))])

    result = await call_llm_json("a prompt", "test-model")

    assert result == {"a": 7}


async def test_call_llm_json_repairs_trailing_comma_and_validates_schema(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A trailing comma is repaired, then the repaired dict passes the schema.

    This drives the schema-injection path (a ``json_schema`` is supplied) and
    the post-repair ``validate_json_schema`` branch in one call. The trailing
    comma is a minor repair, fixed on the first attempt without major repairs.
    """
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message('{"a": 1,}'))])

    result = await call_llm_json("a prompt",
                                 "test-model",
                                 json_schema=_INT_SCHEMA,
                                 max_attempts=2)

    assert result == {"a": 1}


async def test_call_llm_json_unparseable_raises_json_decode_error(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Content that never parses surfaces as ``json.JSONDecodeError``.

    With no schema, garbage content fails ``json.loads``, every repair strategy
    returns ``(None, ...)``, schema validation never runs, and the wrapper
    raises ``json.JSONDecodeError`` after exhausting ``max_attempts``. One
    response is reused for both attempts via the queue below.
    """
    _disable_cache(monkeypatch)
    garbage = _completion(_message("this is not json at all"))
    _patch_acompletion(monkeypatch, [garbage, garbage])

    with pytest.raises(json.JSONDecodeError):
        await call_llm_json("a prompt", "test-model", max_attempts=2)


async def test_call_llm_json_schema_mismatch_raises_validation_error(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Parseable JSON that violates the schema raises ``ValidationError``.

    The content parses cleanly but ``a`` is a string, so schema validation
    fails on every attempt and the wrapper re-raises a ``ValidationError``.
    """
    from jsonschema.exceptions import ValidationError  # pylint: disable=import-outside-toplevel

    _disable_cache(monkeypatch)
    bad = _completion(_message('{"a": "not an int"}'))
    _patch_acompletion(monkeypatch, [bad, bad])

    with pytest.raises(ValidationError):
        await call_llm_json("a prompt",
                            "test-model",
                            json_schema=_INT_SCHEMA,
                            max_attempts=2)


# --- call_llm_with_tools ---------------------------------------------------


async def test_call_llm_with_tools_runs_executor_then_finishes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The tool loop executes a requested tool, then ends on a tool-free reply.

    First completion carries a ``tool_calls`` entry, so ``tool_executor`` runs;
    the second completion has ``tool_calls=None`` (falsy), ending the loop and
    returning the final text. Asserts the executor was invoked with the tool
    call, the final text, and that the history threads through user message,
    assistant tool request, tool result, and final assistant message.
    """
    _disable_cache(monkeypatch)
    first = _completion(
        _message(None, tool_calls=[_tool_call("call-1", "search", '{"q": 1}')]))
    second = _completion(_message("final answer"))
    state = _patch_acompletion(monkeypatch, [first, second])

    seen: list[Any] = []

    async def tool_executor(tc: Any) -> dict[str, Any]:
        seen.append(tc)
        return {
            "role": "tool",
            "tool_call_id": tc.id,
            "content": "tool result",
        }

    tools: list[dict[str, Any]] = [{
        "type": "function",
        "function": {
            "name": "search"
        }
    }]

    final_text, history = await call_llm_with_tools("a prompt",
                                                    "test-model",
                                                    tools=tools,
                                                    tool_executor=tool_executor)

    assert final_text == "final answer"
    assert state["calls"] == 2
    # The executor ran exactly once, on the tool call the model requested.
    assert len(seen) == 1
    assert seen[0].id == "call-1"
    assert seen[0].function.name == "search"
    # History: user -> assistant(tool request) -> tool result -> assistant.
    assert history[0] == {"role": "user", "content": "a prompt"}
    assert history[1]["tool_calls"][0]["id"] == "call-1"
    assert history[2] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "tool result",
    }
    assert history[-1]["content"] == "final answer"


async def test_call_llm_with_tools_no_tool_calls_returns_immediately(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A first reply without tool calls returns at once without the executor."""
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("direct answer"))])

    called = {"ran": False}

    async def tool_executor(_tc: Any) -> dict[str, Any]:
        called["ran"] = True
        return {"role": "tool", "content": ""}

    final_text, history = await call_llm_with_tools("a prompt",
                                                    "test-model",
                                                    tools=[{
                                                        "type": "function",
                                                        "function": {
                                                            "name": "search"
                                                        }
                                                    }],
                                                    tool_executor=tool_executor)

    assert final_text == "direct answer"
    assert called["ran"] is False
    assert history[-1]["content"] == "direct answer"


# --- prompt debug-artifact saving --------------------------------------------


def _enable_real_prompt_saving(monkeypatch: pytest.MonkeyPatch,
                               tmp_path: Path) -> None:
    """Restore the real prompt writer and sandbox its output under tmp_path.

    The autouse ``_no_prompt_disk_writes`` conftest fixture no-ops
    ``prompts.save_prompt_to_disk`` for every test; the wrappers resolve the
    writer through the ``prompts`` module at call time, so re-installing the
    real function (captured at module import, before the fixture ran) makes
    the save observable again. ``get_prompt_save_path`` writes to the relative
    ``.coscientist_prompts/<run_id>/`` directory, so chdir-ing into
    ``tmp_path`` keeps the files out of the working tree.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        tmp_path: The pytest per-test temporary directory.
    """
    monkeypatch.setattr(prompts_mod, "save_prompt_to_disk",
                        _REAL_SAVE_PROMPT_TO_DISK)
    monkeypatch.setenv("COSCIENTIST_SAVE_PROMPTS", "true")
    monkeypatch.chdir(tmp_path)


async def test_call_llm_json_saves_prompt_when_named(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``call_llm_json`` writes the prompt artifact when prompt_name is given.

    The file lands at ``.coscientist_prompts/<run_id>/<prompt_name>.txt`` and
    carries the prompt content plus the appended metadata block.
    """
    _enable_real_prompt_saving(monkeypatch, tmp_path)
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message('{"a": 1}'))])

    result = await call_llm_json(
        "the review prompt",
        "test-model",
        run_id="run-1",
        prompt_name="review_batch",
        prompt_metadata={"hypotheses_count": 3},
    )

    assert result == {"a": 1}
    saved = tmp_path / ".coscientist_prompts" / "run-1" / "review_batch.txt"
    assert saved.exists()
    content = saved.read_text(encoding="utf-8")
    assert content.startswith("the review prompt")
    assert "hypotheses_count: 3" in content


async def test_call_llm_json_does_not_save_without_prompt_name(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Without a prompt_name, ``call_llm_json`` writes no prompt artifact."""
    _enable_real_prompt_saving(monkeypatch, tmp_path)
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message('{"a": 1}'))])

    await call_llm_json("a prompt", "test-model", run_id="run-1")

    assert not (tmp_path / ".coscientist_prompts").exists()


async def test_call_llm_json_run_id_falls_back_to_unknown(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A named prompt with no run_id is saved under the "unknown" directory.

    This is the unified save policy: ``prompt_name`` alone triggers the save;
    a missing ``run_id`` no longer skips it.
    """
    _enable_real_prompt_saving(monkeypatch, tmp_path)
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message('{"a": 1}'))])

    await call_llm_json("a prompt", "test-model", prompt_name="proximity")

    saved = tmp_path / ".coscientist_prompts" / "unknown" / "proximity.txt"
    assert saved.exists()


async def test_call_llm_saves_prompt_when_named(monkeypatch: pytest.MonkeyPatch,
                                                tmp_path: Path) -> None:
    """``call_llm`` shares the same save-when-named policy."""
    _enable_real_prompt_saving(monkeypatch, tmp_path)
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("synthesis text"))])

    await call_llm(
        "the synthesis prompt",
        "test-model",
        run_id="run-2",
        prompt_name="literature_review_synthesis",
    )

    saved = (tmp_path / ".coscientist_prompts" / "run-2" /
             "literature_review_synthesis.txt")
    assert saved.exists()
    assert saved.read_text(encoding="utf-8").startswith("the synthesis prompt")


async def test_call_llm_with_tools_saves_prompt_when_named(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``call_llm_with_tools`` shares the same save-when-named policy."""
    _enable_real_prompt_saving(monkeypatch, tmp_path)
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("done"))])

    async def tool_executor(unused_tc: Any) -> dict[str, Any]:
        return {"role": "tool", "content": ""}

    await call_llm_with_tools(
        "the draft prompt",
        "test-model",
        tools=[{
            "type": "function",
            "function": {
                "name": "search"
            }
        }],
        tool_executor=tool_executor,
        prompt_name="generate_draft_with_tools",
    )

    saved = (tmp_path / ".coscientist_prompts" / "unknown" /
             "generate_draft_with_tools.txt")
    assert saved.exists()
    assert saved.read_text(encoding="utf-8").startswith("the draft prompt")
