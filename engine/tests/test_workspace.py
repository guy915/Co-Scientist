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
from tests._llm_fake import make_tool_call

_requires_sandbox = pytest.mark.skipif(
    sandbox_backend() is None, reason="no sandbox backend on this platform"
)


def _session(tmp_path: Path) -> WorkspaceSession:
    return WorkspaceSession(tmp_path / "ws")


@pytest.mark.asyncio
async def test_a_command_runs_inside_the_workspace(tmp_path: Path) -> None:
    session = _session(tmp_path)
    outcome = await session.run_command(["/bin/pwd"], timeout_seconds=30)
    assert outcome.result.ok, outcome.result.stderr
    assert outcome.result.stdout.strip() == str(session.root)
    assert not outcome.required_approval
    written = await session.run_command(
        ["/usr/bin/touch", "made.txt"], timeout_seconds=30
    )
    assert written.result.ok, written.result.stderr
    assert (session.root / "made.txt").exists()


@pytest.mark.asyncio
async def test_an_unrecognized_command_is_flagged_for_approval(
    tmp_path: Path,
) -> None:
    """The flag records approval intent; sandbox confinement enforces access."""
    session = _session(tmp_path)
    flagged = await session.run_command(
        ["/usr/bin/tee", "out.txt"], timeout_seconds=30
    )
    assert flagged.required_approval


@pytest.mark.asyncio
async def test_a_command_cannot_write_outside_the_workspace(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    escape = tmp_path / "escaped.txt"
    outcome = await session.run_command(
        ["/usr/bin/touch", str(escape)], timeout_seconds=30
    )
    assert not outcome.result.ok
    assert not escape.exists()


@pytest.mark.asyncio
async def test_the_host_environment_is_not_inherited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret")
    session = _session(tmp_path)
    outcome = await session.run_command(["/usr/bin/env"], timeout_seconds=30)
    assert "sk-secret" not in outcome.result.stdout


@pytest.mark.parametrize("path", ["../outside.txt", "sub/../../outside.txt"])
def test_reading_outside_the_workspace_is_refused(
    tmp_path: Path, path: str
) -> None:
    session = _session(tmp_path)
    (tmp_path / "outside.txt").write_text("secret")
    with pytest.raises(PatchError, match="outside the workspace"):
        session.read_file(path)


@_requires_sandbox
@pytest.mark.asyncio
async def test_a_carve_out_backend_refuses_to_replace_the_metadata_dir(
    tmp_path: Path,
) -> None:
    """Landlock only adds access; seatbelt/bwrap can protect writable carve-
    outs."""
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
    """Host writes must reject redirected targets even without backend carve-
    outs."""
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


def test_findings_are_capped(tmp_path: Path) -> None:
    names = []
    for index in range(MAX_FINDINGS + 5):
        name = f"broken_{index}.py"
        (tmp_path / name).write_text("def f(:")
        names.append(name)
    assert len(check_paths(tmp_path, names)) == MAX_FINDINGS


@pytest.fixture
def _isolated_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(WORKSPACE_DIR_ENV, str(tmp_path / "workspaces"))


@pytest.mark.usefixtures("_isolated_root")
class TestRunWorkspace:
    def test_reopening_a_run_returns_the_same_directory(self) -> None:
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
        resolved = workspace_path("../../etc/shadow")
        assert workspaces_root() in resolved.parents

    def test_a_run_id_with_nothing_usable_is_refused(self) -> None:
        with pytest.raises(WorkspaceIdError):
            workspace_path("../..")

    def test_the_workspace_is_the_only_writable_root(self) -> None:
        session = open_run_workspace("run-policy")
        assert session.policy.writable_roots == (session.root,)

    def test_network_is_off_unless_asked_for(self) -> None:
        assert not open_run_workspace("run-net").policy.allows_network
        assert open_run_workspace(
            "run-net-on", network_allowed=True
        ).policy.allows_network

    def test_the_tool_provider_is_bound_to_the_run(self) -> None:
        provider = build_workspace_tools("run-tools")
        assert provider.session.root == workspace_path("run-tools")


def _call(name: str, arguments: Any = "{}") -> SimpleNamespace:
    return make_tool_call(f"call_{name}", name, arguments)


def _provider(tmp_path: Path, **kwargs: Any) -> WorkspaceToolProvider:
    return WorkspaceToolProvider(WorkspaceSession(tmp_path), **kwargs)


def _content(message: dict[str, Any]) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(message["content"])
    return parsed


def _names(schemas: list[dict[str, Any]]) -> list[str]:
    return [schema["function"]["name"] for schema in schemas]


def test_command_tool_is_withheld_without_a_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Offering an unusable tool spends model turns on an unrecoverable
    error."""
    monkeypatch.setattr(workspace_tools, "sandbox_backend", lambda: None)
    schemas = workspace_tool_schemas(workspace_write(tmp_path))
    assert RUN_COMMAND not in _names(schemas)
    assert READ_FILE in _names(schemas)


def test_external_confinement_keeps_the_command_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workspace_tools, "sandbox_backend", lambda: None)
    assert can_run_commands(SandboxPolicy(kind=SandboxKind.EXTERNAL))
    assert can_run_commands(SandboxPolicy(kind=SandboxKind.DANGER_FULL_ACCESS))


class _StubDelegate:
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
    provider = _provider(tmp_path)
    merged = provider.merge_tools(
        [
            {"type": "function", "function": {"name": READ_FILE}},
            {"type": "function", "function": {"name": "search_pubmed"}},
        ]
    )
    assert _names(merged).count(READ_FILE) == 1
    assert "search_pubmed" in _names(merged)


def _loop(names: list[str]) -> ToolLoop:

    async def executor(tool_call: Any) -> dict[str, Any]:
        return {"role": "tool"}

    return ToolLoop(
        tools=[
            {"type": "function", "function": {"name": name}} for name in names
        ],
        executor=executor,
    )


def test_local_tools_disable_the_transcript_cache() -> None:
    guarded = _guard_cache_for_local_tools(
        _loop(["search_pubmed", RUN_COMMAND]), LLMCallOptions(use_cache=True)
    )
    assert guarded.use_cache is False


def test_mcp_only_loops_keep_their_cache() -> None:
    guarded = _guard_cache_for_local_tools(
        _loop(["search_pubmed"]), LLMCallOptions(use_cache=True)
    )
    assert guarded.use_cache is True


@pytest.mark.parametrize(
    ("name", "content", "problem"),
    [
        ("broken.py", "def f(:\n    pass", "SyntaxError"),
        ("config.json", '{"a": ,}', "invalid JSON"),
        ("config.yaml", "a: [1, 2\nb: 3", "invalid YAML"),
        ("fine.py", "VALUE = 1", None),
        ("notes.md", "# heading (", None),
    ],
)
def test_an_edit_comes_back_with_its_syntax_findings(
    tmp_path: Path, name: str, content: str, problem: str | None
) -> None:
    """A parsing veto would prevent writing a program in multiple steps, so
    the finding rides along with a write that still happens."""
    body = [f"+{line}" for line in content.split("\n")]
    payload = _apply(tmp_path, [f"*** Add File: {name}", *body])
    assert payload["changed"] == [name]
    assert (tmp_path / name).exists()
    if problem is None:
        assert "problems" not in payload
    else:
        assert problem in payload["problems"][0]["message"]


def test_a_binary_or_deleted_path_is_not_a_finding(tmp_path: Path) -> None:
    (tmp_path / "blob.json").write_bytes(b"\xff\xfe\x00binary")
    assert check_paths(tmp_path, ["gone.py", "blob.json"]) == ()


@pytest.mark.parametrize(
    ("tool", "arguments", "error"),
    [
        (READ_FILE, {"path": "../outside.txt"}, "outside"),
        (RUN_COMMAND, {"argv": "ls -la | wc -l"}, "bash"),
        (WRITE_FILE, {"path": "model.py"}, "content must be a string"),
        (WRITE_FILE, {"path": "../x.py", "content": "no"}, "outside"),
        ("search_pubmed", {}, "unknown tool"),
        (LIST_FILES, "{not json", "JSON"),
    ],
)
async def test_a_bad_call_is_answered_not_raised(
    tmp_path: Path, tool: str, arguments: Any, error: str
) -> None:
    """Providers reject a transcript containing unanswered tool calls."""
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    result = await _provider(tmp_path).execute_tool_call(_call(tool, raw))
    assert result["tool_call_id"] == f"call_{tool}"
    assert error in _content(result)["error"]
    assert not (tmp_path.parent / "x.py").exists()


async def test_the_file_tools_round_trip_through_tool_calls(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path)

    async def call(name: str, **arguments: Any) -> dict[str, Any]:
        return _content(
            await provider.execute_tool_call(_call(name, json.dumps(arguments)))
        )

    written = await call(WRITE_FILE, path="sub/model.py", content="print(1)\n")
    assert written["bytes"] == len("print(1)\n")
    await call(WRITE_FILE, path="sub/model.py", content="print(2)\n")
    patch = "*** Begin Patch\n*** Add File: hello.py\n+hi\n*** End Patch\n"
    assert (await call(APPLY_PATCH, patch=patch))["changed"] == ["hello.py"]

    assert (await call(READ_FILE, path="sub/model.py"))["content"] == (
        "print(2)\n"
    )
    assert (await call(LIST_FILES))["files"] == ["hello.py", "sub/model.py"]
    # Sibling reads must not observe a half-written workspace tree.
    batches = batch_by_effects(
        [_call(READ_FILE), _call(WRITE_FILE), _call(APPLY_PATCH)]
    )
    assert [len(batch) for batch in batches] == [1, 1, 1]
