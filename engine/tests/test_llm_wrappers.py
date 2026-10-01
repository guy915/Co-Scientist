"""Tests for the network-backed LLM wrappers in ``co_scientist.llm``.

These cover ``call_llm``, ``call_llm_json``, and ``call_llm_with_tools`` -- the
three functions that actually reach out to litellm. The single seam each one
shares is ``litellm.acompletion`` (``call_llm_json`` delegates to ``call_llm``
rather than calling litellm itself), so every test monkeypatches
``litellm.acompletion`` with an async fake that returns a litellm-shaped
response object (a ``SimpleNamespace`` tree mirroring
``response.choices[0].message.{role,content,tool_calls}``). No network is
touched.

Caching is disabled deterministically by patching
``co_scientist.llm.precall.get_cache``
to return a fresh ``LLMCache(enabled=False)``: a disabled cache's ``get`` always
returns ``None`` and ``set`` is a no-op, so each call exercises the real
completion path. Patching the env var is unreliable because ``get_cache``
memoizes a process-global instance that may already exist.

The ``call_llm_with_tools`` tool-loop cases live in
``test_llm_wrappers_tools.py`` and the DeepSeek thinking-mode cases in
``test_llm_wrappers_thinking.py``; the litellm-shaped response fakes
are shared via ``tests/_llm_wrapper_fakes.py``.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from co_scientist import cache as cache_mod
from co_scientist import prompts as prompts_mod
from co_scientist.cache import LLMCache
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm,
    call_llm_json,
    call_llm_with_tools,
    precall,
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
    patch_acompletion as _patch_acompletion,
)

# The real prompt writer, captured at import time -- i.e. before the autouse
# ``_no_prompt_disk_writes`` conftest fixture swaps in its per-test no-op.
_REAL_SAVE_PROMPT_TO_DISK = prompts_mod.save_prompt_to_disk


_INT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
}


# --- call_llm --------------------------------------------------------------
async def test_call_llm_returns_message_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``call_llm`` returns the assistant message content verbatim."""
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("the answer text"))])

    result = await call_llm("a prompt", CompletionSpec(model_name="test-model"))

    assert result == "the answer text"


async def test_call_llm_empty_content_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``call_llm`` raises ``ValueError`` when the model returns empty content.

    The wrapper treats whitespace-only content as empty (``content.strip()``).
    ``max_attempts=1`` keeps this test about the empty-content contract, not
    about the retry ladder (covered by ``test_llm_budget_escalation.py``).
    """
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("   "))])

    with pytest.raises(ValueError, match="None or empty content"):
        await call_llm(
            "a prompt", CompletionSpec(model_name="test-model"), max_attempts=1
        )


async def test_call_llm_invoked_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """``call_llm`` makes exactly one completion call on the happy path."""
    _disable_cache(monkeypatch)
    state = _patch_acompletion(monkeypatch, [_completion(_message("hi"))])

    await call_llm("a prompt", CompletionSpec(model_name="test-model"))

    assert state["calls"] == 1


# --- cache-override scoping (cache.scoped_cache_override) -------------------


async def test_scoped_cache_override_false_skips_get_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task-scoped disable bypasses ``get_cache()`` even for use_cache=True.

    Regression test for the fix to a production bug: a per-generator
    ``enable_cache=False`` used to be applied by mutating
    ``COSCIENTIST_CACHE_ENABLED`` (memoized process-wide by
    ``cache.get_cache()``), so one generator's disabled cache could silently
    disable caching for every other generator in the same process. The fix
    scopes the disable to the current task via
    ``cache.scoped_cache_override`` instead: ``_prepare_llm_call`` must
    consult that per-task override and never even call the memoized
    ``get_cache()`` singleton while it is active.
    """
    calls = {"get_cache": 0}

    def _tracking_get_cache() -> LLMCache:
        calls["get_cache"] += 1
        return LLMCache(enabled=True)

    monkeypatch.setattr(precall, "get_cache", _tracking_get_cache)
    _patch_acompletion(monkeypatch, [_completion(_message("fresh"))])

    with cache_mod.scoped_cache_override(False):
        result = await call_llm(
            "a prompt",
            CompletionSpec(model_name="test-model"),
            options=LLMCallOptions(use_cache=True),
        )

    assert result == "fresh"
    assert calls["get_cache"] == 0


async def test_no_scoped_override_still_uses_get_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no active scope, the process-default ``get_cache()`` is used.

    Companion to the test above: the per-task override must be opt-in, so a
    call made with no ``scoped_cache_override`` active (the common case)
    keeps consulting the process-wide singleton exactly as before.
    """
    calls = {"get_cache": 0}

    def _tracking_get_cache() -> LLMCache:
        calls["get_cache"] += 1
        return LLMCache(enabled=False)

    monkeypatch.setattr(precall, "get_cache", _tracking_get_cache)
    _patch_acompletion(monkeypatch, [_completion(_message("fresh"))])

    await call_llm(
        "a prompt",
        CompletionSpec(model_name="test-model"),
        options=LLMCallOptions(use_cache=True),
    )

    assert calls["get_cache"] == 1


# --- call_llm_json ---------------------------------------------------------


async def test_call_llm_json_parses_clean_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clean JSON content is parsed into a dict and returned."""
    _disable_cache(monkeypatch)
    _patch_acompletion(
        monkeypatch, [_completion(_message('{"a": 1, "b": "x"}'))]
    )

    result = await call_llm_json(
        "a prompt", CompletionSpec(model_name="test-model")
    )

    assert result == {"a": 1, "b": "x"}


async def test_call_llm_json_strips_markdown_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ```json fenced response is unwrapped before parsing.

    Fence stripping lives in ``call_llm_json`` (unlike ``attempt_json_repair``),
    so the inner object is recovered on the first attempt.
    """
    _disable_cache(monkeypatch)
    fenced = '```json\n{"a": 7}\n```'
    _patch_acompletion(monkeypatch, [_completion(_message(fenced))])

    result = await call_llm_json(
        "a prompt", CompletionSpec(model_name="test-model")
    )

    assert result == {"a": 7}


async def test_call_llm_json_repairs_trailing_comma_and_validates_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A trailing comma is repaired, then the repaired dict passes the schema.

    This drives the schema-injection path (a ``json_schema`` is supplied) and
    the post-repair ``validate_json_schema`` branch in one call. The trailing
    comma is a minor repair, fixed on the first attempt without major repairs.
    """
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message('{"a": 1,}'))])

    result = await call_llm_json(
        "a prompt",
        CompletionSpec(model_name="test-model", json_schema=_INT_SCHEMA),
        max_attempts=2,
    )

    assert result == {"a": 1}


async def test_call_llm_json_unparseable_raises_json_decode_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        await call_llm_json(
            "a prompt", CompletionSpec(model_name="test-model"), max_attempts=2
        )


async def test_call_llm_json_schema_mismatch_raises_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parseable JSON that violates the schema raises ``ValidationError``.

    The content parses cleanly but ``a`` is a string, so schema validation
    fails on every attempt and the wrapper re-raises a ``ValidationError``.
    """
    from jsonschema.exceptions import (
        ValidationError,
    )

    _disable_cache(monkeypatch)
    bad = _completion(_message('{"a": "not an int"}'))
    _patch_acompletion(monkeypatch, [bad, bad])

    with pytest.raises(ValidationError):
        await call_llm_json(
            "a prompt",
            CompletionSpec(model_name="test-model", json_schema=_INT_SCHEMA),
            max_attempts=2,
        )


# --- prompt debug-artifact saving --------------------------------------------


def _enable_real_prompt_saving(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
    monkeypatch.setattr(
        prompts_mod, "save_prompt_to_disk", _REAL_SAVE_PROMPT_TO_DISK
    )
    monkeypatch.setenv("COSCIENTIST_SAVE_PROMPTS", "true")
    monkeypatch.chdir(tmp_path)


async def test_call_llm_json_saves_prompt_when_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``call_llm_json`` writes the prompt artifact when prompt_name is given.

    The file lands at ``.coscientist_prompts/<run_id>/<prompt_name>.txt`` and
    carries the prompt content plus the appended metadata block.
    """
    _enable_real_prompt_saving(monkeypatch, tmp_path)
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message('{"a": 1}'))])

    result = await call_llm_json(
        "the review prompt",
        CompletionSpec(model_name="test-model"),
        options=LLMCallOptions(
            run_id="run-1",
            prompt_name="review_batch",
            prompt_metadata={"hypotheses_count": 3},
        ),
    )

    assert result == {"a": 1}
    saved = tmp_path / ".coscientist_prompts" / "run-1" / "review_batch.txt"
    assert saved.exists()
    content = saved.read_text(encoding="utf-8")
    assert content.startswith("the review prompt")
    assert "hypotheses_count: 3" in content


async def test_call_llm_json_does_not_save_without_prompt_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without a prompt_name, ``call_llm_json`` writes no prompt artifact."""
    _enable_real_prompt_saving(monkeypatch, tmp_path)
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message('{"a": 1}'))])

    await call_llm_json(
        "a prompt",
        CompletionSpec(model_name="test-model"),
        options=LLMCallOptions(run_id="run-1"),
    )

    assert not (tmp_path / ".coscientist_prompts").exists()


async def test_call_llm_json_run_id_falls_back_to_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A named prompt with no run_id is saved under the "unknown" directory.

    This is the unified save policy: ``prompt_name`` alone triggers the save;
    a missing ``run_id`` no longer skips it.
    """
    _enable_real_prompt_saving(monkeypatch, tmp_path)
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message('{"a": 1}'))])

    await call_llm_json(
        "a prompt",
        CompletionSpec(model_name="test-model"),
        options=LLMCallOptions(prompt_name="proximity"),
    )

    saved = tmp_path / ".coscientist_prompts" / "unknown" / "proximity.txt"
    assert saved.exists()


async def test_call_llm_saves_prompt_when_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``call_llm`` shares the same save-when-named policy."""
    _enable_real_prompt_saving(monkeypatch, tmp_path)
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("synthesis text"))])

    await call_llm(
        "the synthesis prompt",
        CompletionSpec(model_name="test-model"),
        options=LLMCallOptions(
            run_id="run-2", prompt_name="literature_review_synthesis"
        ),
    )

    saved = (
        tmp_path
        / ".coscientist_prompts"
        / "run-2"
        / "literature_review_synthesis.txt"
    )
    assert saved.exists()
    assert saved.read_text(encoding="utf-8").startswith("the synthesis prompt")


async def test_call_llm_with_tools_saves_prompt_when_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``call_llm_with_tools`` shares the same save-when-named policy."""
    _enable_real_prompt_saving(monkeypatch, tmp_path)
    _disable_cache(monkeypatch)
    _patch_acompletion(monkeypatch, [_completion(_message("done"))])

    async def tool_executor(unused_tc: Any) -> dict[str, Any]:
        return {"role": "tool", "content": ""}

    await call_llm_with_tools(
        "the draft prompt",
        CompletionSpec(model_name="test-model"),
        ToolLoop(tools=_SEARCH_TOOL, executor=tool_executor),
        options=LLMCallOptions(prompt_name="generate_draft_with_tools"),
    )

    saved = (
        tmp_path
        / ".coscientist_prompts"
        / "unknown"
        / "generate_draft_with_tools.txt"
    )
    assert saved.exists()
    assert saved.read_text(encoding="utf-8").startswith("the draft prompt")
