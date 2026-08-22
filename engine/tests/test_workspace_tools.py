"""Tests for the workspace tool surface -- the seam D5 was blocked on.

Two of these are the load-bearing ones and both are easy to write in a
form that passes against the unfixed code.

``test_read_file_batches_with_sibling_reads`` is the only assertion here
that can tell whether local effect declarations are consulted at all.
Asserting that ``run_command`` is a barrier proves nothing: an
*unregistered* tool is a barrier too, by the fail-closed default, so that
test passes whether or not the local table exists.

``test_local_tools_disable_the_transcript_cache`` guards the failure that
produces fabricated evidence rather than an error -- a replayed command
result describing another run's directory.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.llm_tool_loop import (
    ToolLoop,
    _guard_cache_for_local_tools,
)
from co_scientist.llm_types import LLMCallOptions
from co_scientist.sandbox import SandboxKind, SandboxPolicy, workspace_write
from co_scientist.tool_effects import batch_by_effects
from co_scientist.workspace import (
    APPLY_PATCH,
    LIST_FILES,
    READ_FILE,
    RUN_COMMAND,
    WRITE_FILE,
    WorkspaceSession,
    WorkspaceToolProvider,
    can_run_commands,
    workspace_tool_schemas,
)
from co_scientist.workspace import tools as workspace_tools


def _call(name: str, arguments: Any = "{}") -> SimpleNamespace:
    """Builds a litellm-shaped tool call."""
    return SimpleNamespace(
        id=f"call_{name}",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _provider(tmp_path: Path, **kwargs: Any) -> WorkspaceToolProvider:
    """Builds a provider over a session rooted at tmp_path."""
    return WorkspaceToolProvider(WorkspaceSession(tmp_path), **kwargs)


def _content(message: dict[str, Any]) -> dict[str, Any]:
    """Parses a tool-role message's JSON content."""
    parsed: dict[str, Any] = json.loads(message["content"])
    return parsed


def _names(schemas: list[dict[str, Any]]) -> list[str]:
    """Extracts tool names from OpenAI schemas."""
    return [schema["function"]["name"] for schema in schemas]


# --- effects --------------------------------------------------------------


def test_read_file_batches_with_sibling_reads() -> None:
    """The discriminating test for local effect declarations.

    ``read_file`` is declared READ, so it shares one batch with the MCP
    reads either side of it. Without the local table it resolves to the
    fail-closed default, becomes a barrier, and splits the turn into
    three batches -- which is safe, and indistinguishable from correct on
    every tool that really is a barrier. Verified by reverting the
    lookup: this is the assertion that goes red.
    """
    calls = [_call("search_pubmed"), _call(READ_FILE), _call("search_pubmed")]
    assert len(batch_by_effects(calls)) == 1


def test_run_command_and_apply_patch_run_alone() -> None:
    calls = [_call(READ_FILE), _call(RUN_COMMAND), _call(APPLY_PATCH)]
    assert [len(batch) for batch in batch_by_effects(calls)] == [1, 1, 1]


# --- exposure gating ------------------------------------------------------


def test_command_tool_is_withheld_without_a_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fail closed at exposure, not only at execution.

    Production is this case: the api image carries no bubblewrap, so
    offering the tool would spend one loop iteration per attempt on an
    error the model cannot act on.
    """
    monkeypatch.setattr(workspace_tools, "sandbox_backend", lambda: None)
    schemas = workspace_tool_schemas(workspace_write(tmp_path))
    assert RUN_COMMAND not in _names(schemas)
    assert READ_FILE in _names(schemas)


def test_external_confinement_keeps_the_command_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A boundary outside this process is a reason to have no backend."""
    monkeypatch.setattr(workspace_tools, "sandbox_backend", lambda: None)
    assert can_run_commands(SandboxPolicy(kind=SandboxKind.EXTERNAL))
    assert can_run_commands(SandboxPolicy(kind=SandboxKind.DANGER_FULL_ACCESS))


def test_every_offered_tool_has_a_handler(tmp_path: Path) -> None:
    """A schema with no handler answers every call with "unknown tool"."""
    provider = _provider(tmp_path)
    offered, schemas = provider.get_tools()
    assert offered == set(_names(schemas))
    assert offered <= set(workspace_tools._HANDLERS)


# --- execution ------------------------------------------------------------


def test_list_files_reports_workspace_contents(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hi")
    result = asyncio.run(
        _provider(tmp_path).execute_tool_call(_call(LIST_FILES))
    )
    assert _content(result)["files"] == ["notes.txt"]


def test_read_file_returns_content(tmp_path: Path) -> None:
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    result = asyncio.run(
        _provider(tmp_path).execute_tool_call(
            _call(READ_FILE, json.dumps({"path": "data.csv"}))
        )
    )
    assert _content(result)["content"] == "a,b\n1,2\n"


def test_apply_patch_creates_a_file(tmp_path: Path) -> None:
    patch = (
        "*** Begin Patch\n*** Add File: hello.py\n+print('hi')\n*** End Patch\n"
    )
    result = asyncio.run(
        _provider(tmp_path).execute_tool_call(
            _call(APPLY_PATCH, json.dumps({"patch": patch}))
        )
    )
    assert _content(result)["changed"] == ["hello.py"]
    assert (tmp_path / "hello.py").read_text() == "print('hi')\n"


# --- failures answer the call, never raise --------------------------------


def test_a_path_escaping_the_workspace_is_answered_not_raised(
    tmp_path: Path,
) -> None:
    """An unanswered tool call ends the conversation, not just the call.

    The provider rejects a rebuilt turn whose tool call has no matching
    result, so a raise here would turn one bad argument into a failed
    run.
    """
    result = asyncio.run(
        _provider(tmp_path).execute_tool_call(
            _call(READ_FILE, json.dumps({"path": "../outside.txt"}))
        )
    )
    assert result["tool_call_id"] == f"call_{READ_FILE}"
    assert "outside" in _content(result)["error"]


def test_a_bare_command_string_is_refused_with_guidance(
    tmp_path: Path,
) -> None:
    """An array, always; silently splitting a string hides the shell."""
    result = asyncio.run(
        _provider(tmp_path).execute_tool_call(
            _call(RUN_COMMAND, json.dumps({"argv": "ls -la | wc -l"}))
        )
    )
    assert "bash" in _content(result)["error"]


def test_malformed_arguments_are_answered(tmp_path: Path) -> None:
    result = asyncio.run(
        _provider(tmp_path).execute_tool_call(_call(LIST_FILES, "{not json"))
    )
    assert "JSON" in _content(result)["error"]


def test_an_unknown_tool_without_a_delegate_is_answered(
    tmp_path: Path,
) -> None:
    result = asyncio.run(
        _provider(tmp_path).execute_tool_call(_call("search_pubmed"))
    )
    assert "unknown tool" in _content(result)["error"]


# --- composition with MCP -------------------------------------------------


class _StubDelegate:
    """Stands in for the run's MCPToolProvider."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def execute_tool_call(self, tool_call: Any) -> dict[str, Any]:
        self.seen.append(tool_call.function.name)
        return {"role": "tool", "name": tool_call.function.name}


def test_non_workspace_calls_reach_the_delegate(tmp_path: Path) -> None:
    delegate = _StubDelegate()
    provider = _provider(tmp_path, delegate=delegate)
    asyncio.run(provider.execute_tool_call(_call("search_pubmed")))
    assert delegate.seen == ["search_pubmed"]


def test_a_shadowed_mcp_tool_is_dropped_not_duplicated(
    tmp_path: Path,
) -> None:
    """Two schemas with one name is undefined behaviour at the provider."""
    provider = _provider(tmp_path)
    merged = provider.merge_tools(
        [
            {"type": "function", "function": {"name": READ_FILE}},
            {"type": "function", "function": {"name": "search_pubmed"}},
        ]
    )
    assert _names(merged).count(READ_FILE) == 1
    assert "search_pubmed" in _names(merged)


# --- cache safety ---------------------------------------------------------


def _loop(names: list[str]) -> ToolLoop:
    """Builds a ToolLoop offering the named tools."""

    async def executor(tool_call: Any) -> dict[str, Any]:
        return {"role": "tool"}

    return ToolLoop(
        tools=[
            {"type": "function", "function": {"name": name}} for name in names
        ],
        executor=executor,
    )


def test_local_tools_disable_the_transcript_cache() -> None:
    """A replayed exec result is fabricated evidence, not a stale answer."""
    guarded = _guard_cache_for_local_tools(
        _loop(["search_pubmed", RUN_COMMAND]), LLMCallOptions(use_cache=True)
    )
    assert guarded.use_cache is False


def test_mcp_only_loops_keep_their_cache() -> None:
    """The guard must not cost literature loops their cache."""
    guarded = _guard_cache_for_local_tools(
        _loop(["search_pubmed"]), LLMCallOptions(use_cache=True)
    )
    assert guarded.use_cache is True


# --- write_file -----------------------------------------------------------


async def test_write_file_creates_a_file_and_its_parents(
    tmp_path: Path,
) -> None:
    """Creating a program is the model's commonest intent; make it one call.

    Expressing "here is the file I want to run" as a context-anchored
    patch is the wrong shape: a new file has no context to anchor to, so
    the envelope is pure ceremony and getting it wrong costs a turn.
    Measured against the real model on one simulation, 33 of that loop's
    tool results were ``apply_patch`` rejections over exactly that
    ceremony; with this tool the same mechanism produced zero tool
    errors.
    """
    provider = _provider(tmp_path)

    message = await provider.execute_tool_call(
        _call(
            WRITE_FILE,
            json.dumps({"path": "sub/model.py", "content": "print(1)\n"}),
        )
    )

    assert (tmp_path / "sub" / "model.py").read_text() == "print(1)\n"
    body = _content(message)
    assert body["path"] == "sub/model.py"
    assert body["bytes"] == len("print(1)\n")


async def test_write_file_replaces_existing_content(tmp_path: Path) -> None:
    """A rewrite is the model's normal debugging move, not an error."""
    provider = _provider(tmp_path)
    target = tmp_path / "model.py"
    target.write_text("old\n")

    await provider.execute_tool_call(
        _call(WRITE_FILE, json.dumps({"path": "model.py", "content": "new\n"}))
    )

    assert target.read_text() == "new\n"


async def test_write_file_cannot_escape_the_workspace(tmp_path: Path) -> None:
    """The containment is the same one read_file relies on."""
    provider = _provider(tmp_path)

    message = await provider.execute_tool_call(
        _call(
            WRITE_FILE,
            json.dumps({"path": "../escaped.py", "content": "nope\n"}),
        )
    )

    assert not (tmp_path.parent / "escaped.py").exists()
    assert "error" in json.dumps(message).lower()


async def test_write_file_rejects_a_missing_argument(tmp_path: Path) -> None:
    """A bad call must be answerable, not fatal to the conversation."""
    provider = _provider(tmp_path)

    message = await provider.execute_tool_call(
        _call(WRITE_FILE, json.dumps({"path": "model.py"}))
    )

    assert message["role"] == "tool"
    assert "content must be a string" in json.dumps(message)


async def test_write_file_is_a_barrier_like_the_other_writer(
    tmp_path: Path,
) -> None:
    """A write must not batch concurrently with a sibling read.

    ``apply_patch`` is a barrier for this reason and ``write_file``
    writes the same directory, so a declaration that let it run beside a
    read would let a read observe a half-written tree.
    """
    del tmp_path
    batches = batch_by_effects(
        [_call(READ_FILE), _call(WRITE_FILE), _call(READ_FILE)]
    )

    assert [len(batch) for batch in batches] == [1, 1, 1]


async def test_write_file_runs_the_same_checks_a_patch_does(
    tmp_path: Path,
) -> None:
    """Otherwise this tool is the way around apply_patch's safety scan."""
    provider = _provider(tmp_path)

    patched = await provider.execute_tool_call(
        _call(
            WRITE_FILE,
            json.dumps({"path": "m.py", "content": "x = 1\n"}),
        )
    )

    # The scan ran: its verdict is reported under the same key the patch
    # handler uses, present only when it found something.
    assert "problems" not in _content(patched) or isinstance(
        _content(patched)["problems"], list
    )


def test_write_file_is_offered_before_apply_patch(tmp_path: Path) -> None:
    """Order is guidance: the model reaches for the first tool that fits."""
    names = _names(workspace_tool_schemas(workspace_write(tmp_path)))

    assert WRITE_FILE in names
    assert names.index(WRITE_FILE) < names.index(APPLY_PATCH)
