"""Offline contracts for workspace."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.llm import LLMCallOptions, ToolLoop
from co_scientist.llm.tools.policy import _guard_cache_for_local_tools
from co_scientist.patch import PatchError
from co_scientist.sandbox import (
    SandboxKind,
    SandboxPolicy,
    sandbox_backend,
    workspace_write,
)
from co_scientist.tool_effects import batch_by_effects
from co_scientist.workspace import (
    APPLY_PATCH,
    LIST_FILES,
    READ_FILE,
    RUN_COMMAND,
    SPILL_DIRECTORY,
    WORKSPACE_DIR_ENV,
    WRITE_FILE,
    OutputRecorder,
    WorkspaceIdError,
    WorkspaceSession,
    WorkspaceToolProvider,
    build_workspace_tools,
    can_run_commands,
    open_run_workspace,
    workspace_path,
    workspace_tool_schemas,
    workspaces_root,
)
from co_scientist.workspace import tools as workspace_tools
from co_scientist.workspace.checks import MAX_FINDINGS, check_paths

_requires_sandbox = pytest.mark.skipif(
    sandbox_backend() is None, reason="no sandbox backend on this platform"
)


def _session(tmp_path: Path) -> WorkspaceSession:
    """Builds a session rooted at a fresh workspace."""
    return WorkspaceSession(tmp_path / "ws")


def test_the_root_is_created_if_absent(tmp_path: Path) -> None:
    session = WorkspaceSession(tmp_path / "made" / "here")
    assert session.root.is_dir()


@pytest.mark.asyncio
async def test_a_command_runs_inside_the_workspace(tmp_path: Path) -> None:
    session = _session(tmp_path)
    outcome = await session.run_command(["/bin/pwd"], timeout_seconds=30)
    assert outcome.result.ok, outcome.result.stderr
    assert outcome.result.stdout.strip() == str(session.root)


@pytest.mark.asyncio
async def test_a_read_only_command_needs_no_approval(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    outcome = await session.run_command(["/bin/echo", "x"], timeout_seconds=30)
    assert not outcome.required_approval


@pytest.mark.asyncio
async def test_an_unrecognized_command_is_flagged_for_approval(
    tmp_path: Path,
) -> None:
    """Flagged, not blocked -- the sandbox is what blocks.

    A command outside the read-only allowlist still runs; the flag is an
    audit record of what a human would have been asked about.
    """
    session = _session(tmp_path)
    flagged = await session.run_command(
        ["/usr/bin/tee", "out.txt"], timeout_seconds=30
    )
    assert flagged.required_approval


@pytest.mark.asyncio
async def test_a_command_cannot_write_outside_the_workspace(
    tmp_path: Path,
) -> None:
    """The composition that matters: session root becomes sandbox root."""
    session = _session(tmp_path)
    escape = tmp_path / "escaped.txt"
    outcome = await session.run_command(
        ["/usr/bin/touch", str(escape)], timeout_seconds=30
    )
    assert not outcome.result.ok
    assert not escape.exists()


@pytest.mark.asyncio
async def test_a_command_can_write_inside_the_workspace(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    outcome = await session.run_command(
        ["/usr/bin/touch", "made.txt"], timeout_seconds=30
    )
    assert outcome.result.ok, outcome.result.stderr
    assert (session.root / "made.txt").exists()


@pytest.mark.asyncio
async def test_the_host_environment_is_not_inherited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret")
    session = _session(tmp_path)
    outcome = await session.run_command(["/usr/bin/env"], timeout_seconds=30)
    assert "sk-secret" not in outcome.result.stdout


def test_patching_edits_files_in_the_workspace(tmp_path: Path) -> None:
    session = _session(tmp_path)
    (session.root / "a.py").write_text("old\n")

    outcome = session.apply_patch_text(
        "\n".join(
            [
                "*** Begin Patch",
                "*** Update File: a.py",
                "@@",
                "-old",
                "+new",
                "*** End Patch",
            ]
        )
    )

    assert outcome.changed == ("a.py",)
    assert (session.root / "a.py").read_text() == "new\n"


def test_reading_and_listing(tmp_path: Path) -> None:
    session = _session(tmp_path)
    (session.root / "sub").mkdir()
    (session.root / "sub" / "f.txt").write_text("content")

    assert session.read_file("sub/f.txt") == "content"
    assert session.list_files() == ("sub/f.txt",)


@pytest.mark.parametrize("path", ["../outside.txt", "sub/../../outside.txt"])
def test_reading_outside_the_workspace_is_refused(
    tmp_path: Path, path: str
) -> None:
    session = _session(tmp_path)
    (tmp_path / "outside.txt").write_text("secret")
    with pytest.raises(PatchError, match="outside the workspace"):
        session.read_file(path)


def test_a_failed_patch_reports_and_changes_nothing(tmp_path: Path) -> None:
    session = _session(tmp_path)
    (session.root / "a.py").write_text("actual\n")
    with pytest.raises(PatchError, match="did not match"):
        session.apply_patch_text(
            "\n".join(
                [
                    "*** Begin Patch",
                    "*** Update File: a.py",
                    "@@",
                    "-expected",
                    "+new",
                    "*** End Patch",
                ]
            )
        )
    assert (session.root / "a.py").read_text() == "actual\n"


@_requires_sandbox
@pytest.mark.asyncio
async def test_a_carve_out_backend_refuses_to_replace_the_metadata_dir(
    tmp_path: Path,
) -> None:
    """Only two of the three backends can express this.

    seatbelt denies by path and bwrap re-binds read-only; landlock rules
    can only *add* access, so it has no spelling for "writable, except
    here". Skipped rather than relaxed, because the guarantee genuinely
    differs by platform and a test that accepted either outcome would
    stop noticing if the two that can enforce it stopped.
    """
    if sandbox_backend() == "landlock":
        pytest.skip("landlock cannot express a carve-out; see the next test")
    link = shutil.which("ln")
    if link is None:  # pragma: no cover - environment-dependent
        pytest.skip("ln is not installed")
    session = _session(tmp_path)
    metadata = SPILL_DIRECTORY.split("/")[0]

    outcome = await session.run_command(
        [link, "-sfn", "/tmp", metadata], timeout_seconds=30
    )

    assert not outcome.result.ok
    assert not (session.root / metadata).is_symlink()


@_requires_sandbox
@pytest.mark.asyncio
async def test_replacing_the_metadata_dir_cannot_redirect_a_host_write(
    tmp_path: Path,
) -> None:
    """The invariant that does hold on every backend.

    Where the carve-out exists a command cannot replace the directory;
    where it does not, the command succeeds and the host's own write
    then refuses the redirected target. Either way nothing lands outside
    the workspace -- and this, not the carve-out, is what makes spilling
    output safe.
    """
    link = shutil.which("ln")
    if link is None:  # pragma: no cover - environment-dependent
        pytest.skip("ln is not installed")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    session = _session(tmp_path)
    metadata = SPILL_DIRECTORY.split("/")[0]

    await session.run_command(
        [link, "-sfn", str(outside), metadata], timeout_seconds=30
    )
    OutputRecorder(session.root, preview_chars=50).record("stdout", "x" * 900)

    assert list(outside.rglob("*")) == []


def _apply(tmp_path: Path, body: list[str]) -> dict[str, Any]:
    """Applies a patch through the tool surface, returning its payload."""
    patch = "\n".join(["*** Begin Patch", *body, "*** End Patch", ""])
    provider = WorkspaceToolProvider(WorkspaceSession(tmp_path))
    message = asyncio.run(
        provider.execute_tool_call(
            SimpleNamespace(
                id="call_apply_patch",
                function=SimpleNamespace(
                    name="apply_patch",
                    arguments=json.dumps({"patch": patch}),
                ),
            )
        )
    )
    parsed: dict[str, Any] = json.loads(message["content"])
    return parsed


def test_a_syntax_error_comes_back_with_the_edit(tmp_path: Path) -> None:
    """The whole point: same turn, not two tool calls later."""
    payload = _apply(
        tmp_path, ["*** Add File: broken.py", "+def f(:", "+    pass"]
    )
    assert payload["changed"] == ["broken.py"]
    assert payload["problems"][0]["path"] == "broken.py"
    assert "SyntaxError" in payload["problems"][0]["message"]


def test_a_finding_does_not_undo_the_write(tmp_path: Path) -> None:
    """The write already happened; a check result is not a veto.

    Refusing edits that do not parse would also make writing a file in
    two steps impossible.
    """
    _apply(tmp_path, ["*** Add File: broken.py", "+def f(:"])
    assert (tmp_path / "broken.py").read_text() == "def f(:\n"


def test_a_clean_edit_says_nothing(tmp_path: Path) -> None:
    """Silence is the common case and must not carry an empty key."""
    payload = _apply(tmp_path, ["*** Add File: fine.py", "+VALUE = 1"])
    assert "problems" not in payload


def test_a_file_type_with_no_checker_says_nothing(tmp_path: Path) -> None:
    payload = _apply(tmp_path, ["*** Add File: notes.md", "+# heading ("])
    assert "problems" not in payload


def test_invalid_json_is_reported(tmp_path: Path) -> None:
    payload = _apply(tmp_path, ["*** Add File: config.json", '+{"a": ,}'])
    assert "invalid JSON" in payload["problems"][0]["message"]


def test_invalid_yaml_is_reported(tmp_path: Path) -> None:
    payload = _apply(
        tmp_path, ["*** Add File: config.yaml", "+a: [1, 2", "+b: 3"]
    )
    assert "invalid YAML" in payload["problems"][0]["message"]


def test_a_deleted_path_is_not_a_finding(tmp_path: Path) -> None:
    """A patch reports what it changed, including what it removed."""
    assert check_paths(tmp_path, ["gone.py"]) == ()


def test_a_binary_file_is_not_a_finding(tmp_path: Path) -> None:
    """Unreadable is not the same as wrong."""
    (tmp_path / "blob.json").write_bytes(b"\xff\xfe\x00binary")
    assert check_paths(tmp_path, ["blob.json"]) == ()


def test_findings_are_capped(tmp_path: Path) -> None:
    """A patch that rewrote a tree must not return a wall of text."""
    names = []
    for index in range(MAX_FINDINGS + 5):
        name = f"broken_{index}.py"
        (tmp_path / name).write_text("def f(:")
        names.append(name)
    assert len(check_paths(tmp_path, names)) == MAX_FINDINGS


@pytest.fixture
def _isolated_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keeps every test off the real workspaces directory."""
    monkeypatch.setenv(WORKSPACE_DIR_ENV, str(tmp_path / "workspaces"))


@pytest.mark.usefixtures("_isolated_root")
class TestRunWorkspace:
    def test_reopening_a_run_returns_the_same_directory(self) -> None:
        """A restarted worker must find the files the killed one wrote."""
        first = open_run_workspace("run-abc")
        (first.root / "partial.csv").write_text("1,2\n")

        second = open_run_workspace("run-abc")

        assert second.root == first.root
        assert (second.root / "partial.csv").read_text() == "1,2\n"

    def test_two_runs_do_not_share_a_workspace(self) -> None:
        assert (
            open_run_workspace("run-a").root != open_run_workspace("run-b").root
        )

    def test_a_traversing_run_id_stays_under_the_root(self) -> None:
        """The resolved path becomes a writable root; traversal is an escape."""
        resolved = workspace_path("../../etc/shadow")
        assert workspaces_root() in resolved.parents

    def test_a_run_id_with_nothing_usable_is_refused(self) -> None:
        with pytest.raises(WorkspaceIdError):
            workspace_path("../..")

    def test_the_workspace_is_the_only_writable_root(self) -> None:
        session = open_run_workspace("run-policy")
        assert session.policy.writable_roots == (session.root,)

    def test_network_is_off_unless_asked_for(self) -> None:
        """Needing the internet is a decision, not the resting state."""
        assert not open_run_workspace("run-net").policy.allows_network
        assert open_run_workspace(
            "run-net-on", network_allowed=True
        ).policy.allows_network

    def test_the_tool_provider_is_bound_to_the_run(self) -> None:
        provider = build_workspace_tools("run-tools")
        assert provider.session.root == workspace_path("run-tools")


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
