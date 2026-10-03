from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist.sandbox import (
    HARNESS_METADATA_NAME,
    METADATA_NAMES,
    PROTECTED_METADATA_NAMES,
    sandbox_backend,
)
from co_scientist.workspace import (
    LIST_FILES,
    MIN_SECRET_LENGTH,
    READ_FILE,
    SPILL_DIRECTORY,
    OutputRecorder,
    SecretRegistrationError,
    SecretRegistry,
    WorkspaceSession,
    WorkspaceToolProvider,
)
from co_scientist.workspace import RUN_COMMAND as _WORKSPACE_OUTPUT_RUN_COMMAND
from co_scientist.workspace.session import (
    MAX_SESSION_OUTPUT_BYTES,
    SessionRegistry,
)
from co_scientist.workspace.tool_schemas import POLL_COMMAND
from co_scientist.workspace.tool_schemas import (
    RUN_COMMAND as _WORKSPACE_SESSIONS_RUN_COMMAND,
)


def _workspace_sessions_call(name: str, arguments: Any) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"call_{name}",
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


async def _execute(
    provider: WorkspaceToolProvider, name: str, **arguments: Any
) -> dict[str, Any]:
    message = await provider.execute_tool_call(
        _workspace_sessions_call(name, arguments)
    )
    parsed: dict[str, Any] = json.loads(message["content"])
    return parsed


async def _wait_for_output(
    provider: WorkspaceToolProvider,
    payload: dict[str, Any],
    needle: str,
    *,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """A loaded host or sandbox re-exec can outlast a yield window; bounded
    polling resolves that race."""
    deadline = time.monotonic() + timeout
    while needle not in payload["stdout"]:
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"{needle!r} did not appear in stdout within {timeout}s"
            )
        payload = await _execute(
            provider,
            POLL_COMMAND,
            session_id=payload["session_id"],
            cursor=payload["cursor"],
            wait_seconds=0.5,
        )
    return payload


@pytest.fixture
def provider(tmp_path: Path) -> WorkspaceToolProvider:
    return WorkspaceToolProvider(WorkspaceSession(tmp_path))


class TestStillRunningIsAnAnswer:
    async def test_a_slow_command_comes_back_with_a_session(
        self, provider: WorkspaceToolProvider
    ) -> None:
        payload = await _execute(
            provider,
            _WORKSPACE_SESSIONS_RUN_COMMAND,
            argv=["bash", "-c", "echo early; sleep 30"],
            yield_seconds=0.4,
        )
        assert payload["running"] is True
        assert payload["session_id"]
        payload = await _wait_for_output(provider, payload, "early")
        assert "early" in payload["stdout"]
        # End the deliberately surviving command rather than leaking it past the
        # test.
        await provider.session.sessions.close()

    async def test_a_fast_command_finishes_in_one_call(
        self, provider: WorkspaceToolProvider
    ) -> None:
        payload = await _execute(
            provider,
            _WORKSPACE_SESSIONS_RUN_COMMAND,
            argv=["bash", "-lc", "echo hi"],
        )
        assert payload["running"] is False
        assert payload["exit_code"] == 0
        assert "hi" in payload["stdout"]

    async def test_polling_carries_it_to_its_exit_code(
        self, provider: WorkspaceToolProvider
    ) -> None:
        started = await _execute(
            provider,
            _WORKSPACE_SESSIONS_RUN_COMMAND,
            argv=["bash", "-lc", "sleep 0.3; echo done; exit 7"],
            yield_seconds=0.05,
        )
        polled = await _execute(
            provider,
            POLL_COMMAND,
            session_id=started["session_id"],
            cursor=started["cursor"],
            wait_seconds=10,
        )
        assert polled["running"] is False
        assert polled["exit_code"] == 7
        assert "done" in polled["stdout"]

    async def test_the_cursor_does_not_repeat_output(
        self, provider: WorkspaceToolProvider
    ) -> None:
        # Cursor advancement prevents quadratic replay; gating the second line
        # removes yield races.
        started = await _execute(
            provider,
            _WORKSPACE_SESSIONS_RUN_COMMAND,
            argv=["bash", "-c", "echo first; read line; echo second"],
            yield_seconds=0.1,
        )
        started = await _wait_for_output(provider, started, "first")
        assert "first" in started["stdout"]
        polled = await _execute(
            provider,
            POLL_COMMAND,
            session_id=started["session_id"],
            cursor=started["cursor"],
            input="go\n",
            wait_seconds=10,
        )
        assert "second" in polled["stdout"]
        assert "first" not in polled["stdout"]

    async def test_no_cursor_reads_from_the_start(
        self, provider: WorkspaceToolProvider
    ) -> None:
        started = await _execute(
            provider,
            _WORKSPACE_SESSIONS_RUN_COMMAND,
            argv=["bash", "-lc", "echo whole"],
        )
        polled = await _execute(
            provider, POLL_COMMAND, session_id=started["session_id"]
        )
        assert "whole" in polled["stdout"]


class TestDrivingIt:
    async def test_input_reaches_a_waiting_command(
        self, provider: WorkspaceToolProvider
    ) -> None:
        started = await _execute(
            provider,
            _WORKSPACE_SESSIONS_RUN_COMMAND,
            argv=["bash", "-lc", "read line; echo got:$line"],
            yield_seconds=0.05,
        )
        polled = await _execute(
            provider,
            POLL_COMMAND,
            session_id=started["session_id"],
            cursor=started["cursor"],
            input="hello\n",
            wait_seconds=10,
        )
        assert "got:hello" in polled["stdout"]

    async def test_kill_ends_it(self, provider: WorkspaceToolProvider) -> None:
        started = await _execute(
            provider,
            _WORKSPACE_SESSIONS_RUN_COMMAND,
            argv=["bash", "-lc", "sleep 60"],
            yield_seconds=0.05,
        )
        killed = await _execute(
            provider,
            POLL_COMMAND,
            session_id=started["session_id"],
            kill=True,
        )
        assert killed["running"] is False

    async def test_input_to_a_finished_command_is_refused_legibly(
        self, provider: WorkspaceToolProvider
    ) -> None:
        """Invalid model input is a tool error, not an exception that fails
        sibling calls."""
        started = await _execute(
            provider,
            _WORKSPACE_SESSIONS_RUN_COMMAND,
            argv=["bash", "-lc", "read line; echo got:$line"],
            yield_seconds=0.05,
        )
        await _execute(
            provider,
            POLL_COMMAND,
            session_id=started["session_id"],
            input="first\n",
            wait_seconds=10,
        )
        late = await _execute(
            provider,
            POLL_COMMAND,
            session_id=started["session_id"],
            input="second\n",
        )
        assert "not accepting input" in json.dumps(late)
        assert "tool execution failed" not in json.dumps(late)
        again = await _execute(
            provider, POLL_COMMAND, session_id=started["session_id"]
        )
        assert "got:first" in again["stdout"]

    async def test_an_unknown_session_says_why(
        self, provider: WorkspaceToolProvider
    ) -> None:
        payload = await _execute(provider, POLL_COMMAND, session_id="nope")
        assert "restart" in json.dumps(payload)


class TestBounds:
    async def test_output_is_capped_and_says_so(self, tmp_path: Path) -> None:
        registry = SessionRegistry()
        session_ws = WorkspaceSession(tmp_path)
        session = await registry.start(
            [
                "bash",
                "-lc",
                f"head -c {MAX_SESSION_OUTPUT_BYTES * 2} /dev/zero | tr "
                "'\\0' 'x'",
            ],
            policy=session_ws.policy,
            cwd=session_ws.root,
        )
        await session.wait_for(20)
        read = session.read()
        assert read.truncated["stdout"] is True
        assert len(read.stdout) <= MAX_SESSION_OUTPUT_BYTES
        await registry.close()

    async def test_closing_the_registry_ends_a_live_command(
        self, tmp_path: Path
    ) -> None:
        session_ws = WorkspaceSession(tmp_path)
        registry = SessionRegistry()
        session = await registry.start(
            ["bash", "-lc", "sleep 60"],
            policy=session_ws.policy,
            cwd=session_ws.root,
        )
        assert session.running
        await registry.close()
        await asyncio.sleep(0.05)
        assert not session.running

    async def test_too_many_live_commands_is_refused(
        self, tmp_path: Path
    ) -> None:
        session_ws = WorkspaceSession(tmp_path)
        registry = SessionRegistry()
        for _ in range(4):
            await registry.start(
                ["bash", "-lc", "sleep 60"],
                policy=session_ws.policy,
                cwd=session_ws.root,
            )
        with pytest.raises(RuntimeError, match="already running"):
            await registry.start(
                ["bash", "-lc", "sleep 60"],
                policy=session_ws.policy,
                cwd=session_ws.root,
            )
        await registry.close()


class TestAnInterruptedCommand:
    """Worker restarts lose sessions; the model needs explicit aborts, not
    unmatched calls."""

    async def test_the_resumed_transcript_says_the_call_was_aborted(
        self, tmp_path: Path
    ) -> None:
        from co_scientist.llm.tools.transcript import (
            ABORTED_RESULT,
            normalize_tool_transcript,
        )

        provider = WorkspaceToolProvider(WorkspaceSession(tmp_path))
        started = await _execute(
            provider,
            _WORKSPACE_SESSIONS_RUN_COMMAND,
            argv=["bash", "-lc", "sleep 60"],
            yield_seconds=0.05,
        )
        assert started["running"] is True

        interrupted = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_poll",
                        "type": "function",
                        "function": {
                            "name": POLL_COMMAND,
                            "arguments": json.dumps(
                                {"session_id": started["session_id"]}
                            ),
                        },
                    }
                ],
            }
        ]
        await provider.session.sessions.close()

        repaired = normalize_tool_transcript(interrupted)
        assert repaired[1]["tool_call_id"] == "call_poll"
        assert json.loads(repaired[1]["content"]) == ABORTED_RESULT

    async def test_polling_a_session_the_restart_ended_is_legible(
        self, tmp_path: Path
    ) -> None:
        provider = WorkspaceToolProvider(WorkspaceSession(tmp_path))
        started = await _execute(
            provider,
            _WORKSPACE_SESSIONS_RUN_COMMAND,
            argv=["bash", "-lc", "sleep 60"],
            yield_seconds=0.05,
        )
        await provider.session.sessions.close()
        payload = await _execute(
            provider, POLL_COMMAND, session_id=started["session_id"]
        )
        assert "restart" in json.dumps(payload)


_requires_sandbox = pytest.mark.skipif(
    sandbox_backend() is None, reason="no sandbox backend on this platform"
)

_SECRET = "sk-live-9f3c2b71aa4d8e60"


def _workspace_output_call(name: str, arguments: Any = "{}") -> SimpleNamespace:
    return SimpleNamespace(
        id=f"call_{name}",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _registry(**secrets: str) -> SecretRegistry:
    registry = SecretRegistry()
    for name, value in secrets.items():
        registry.register(name, value)
    return registry


def _content(message: dict[str, Any]) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(message["content"])
    return parsed


def _run(provider: WorkspaceToolProvider, argv: list[str]) -> dict[str, Any]:
    return _content(
        asyncio.run(
            provider.execute_tool_call(
                _workspace_output_call(
                    _WORKSPACE_OUTPUT_RUN_COMMAND, json.dumps({"argv": argv})
                )
            )
        )
    )


def test_a_short_value_is_refused_rather_than_masked() -> None:
    with pytest.raises(SecretRegistrationError, match="cannot be masked"):
        _registry(TOKEN="a" * (MIN_SECRET_LENGTH - 1))


def test_environment_scan_finds_credential_shaped_names() -> None:
    registry = SecretRegistry()
    found = registry.register_environment(
        {
            "ANTHROPIC_API_KEY": _SECRET,
            "GITHUB_TOKEN": "ghp_0123456789abcdef",
            "PATH": "/usr/bin",
        }
    )
    assert set(found) == {"ANTHROPIC_API_KEY", "GITHUB_TOKEN"}


def test_environment_scan_skips_a_short_value_without_raising() -> None:
    registry = SecretRegistry()
    found = registry.register_environment(
        {"SHORT_KEY": "abc", "REAL_KEY": _SECRET}
    )
    assert found == ("REAL_KEY",)


def test_a_secret_containing_another_is_masked_as_itself() -> None:
    registry = _registry(INNER=_SECRET, OUTER=f"{_SECRET}-extended-suffix")
    assert registry.redact(f"{_SECRET}-extended-suffix") == "[redacted:OUTER]"


@_requires_sandbox
def test_a_command_printing_a_secret_does_not_print_it(tmp_path: Path) -> None:
    """Command stdout enters the transcript directly and must redact injected
    credentials."""
    echo = shutil.which("echo")
    if echo is None:  # pragma: no cover - environment-dependent
        pytest.skip("echo is not installed")
    provider = WorkspaceToolProvider(
        WorkspaceSession(tmp_path), secrets=_registry(API_KEY=_SECRET)
    )

    payload = _run(provider, [echo, _SECRET])

    assert _SECRET not in json.dumps(payload)
    assert "[redacted:API_KEY]" in payload["stdout"]


def test_reading_a_file_does_not_route_around_redaction(
    tmp_path: Path,
) -> None:
    (tmp_path / "captured.txt").write_text(f"key={_SECRET}\n")
    provider = WorkspaceToolProvider(
        WorkspaceSession(tmp_path), secrets=_registry(API_KEY=_SECRET)
    )

    payload = _content(
        asyncio.run(
            provider.execute_tool_call(
                _workspace_output_call(
                    READ_FILE, json.dumps({"path": "captured.txt"})
                )
            )
        )
    )

    assert _SECRET not in payload["content"]


def test_output_is_dropped_whole_when_a_value_survives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fault injection proves the fail-closed guard still works if redaction
    fails."""
    monkeypatch.setattr(SecretRegistry, "redact", lambda self, text: text)
    recorder = OutputRecorder(tmp_path, _registry(API_KEY=_SECRET))

    bounded = recorder.record("stdout", f"leaked {_SECRET}")

    assert _SECRET not in bounded.text
    assert "API_KEY" in bounded.text
    assert bounded.truncated


def test_a_long_stream_keeps_both_ends(tmp_path: Path) -> None:
    recorder = OutputRecorder(tmp_path, preview_chars=200)
    text = f"START{'x' * 5000}END"

    bounded = recorder.record("stdout", text)

    assert bounded.text.startswith("START")
    assert bounded.text.endswith("END")
    assert bounded.truncated


def test_spilled_output_is_readable_back_through_the_tools(
    tmp_path: Path,
) -> None:
    session = WorkspaceSession(tmp_path)
    provider = WorkspaceToolProvider(session)
    recorder = OutputRecorder(session.root, preview_chars=100)
    text = f"START{'x' * 5000}END"

    pointer = recorder.record("stdout", text).pointer
    assert pointer is not None

    payload = _content(
        asyncio.run(
            provider.execute_tool_call(
                _workspace_output_call(
                    READ_FILE, json.dumps({"path": pointer.path})
                )
            )
        )
    )
    assert payload["content"] == text


def test_spilled_output_is_redacted_before_it_is_written(
    tmp_path: Path,
) -> None:
    recorder = OutputRecorder(
        tmp_path, _registry(API_KEY=_SECRET), preview_chars=100
    )

    pointer = recorder.record("stdout", f"{_SECRET}{'x' * 5000}").pointer

    assert pointer is not None
    assert _SECRET not in (tmp_path / pointer.path).read_text()


def test_a_failed_spill_costs_the_middle_not_the_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:

    def _explode(*args: Any, **kwargs: Any) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr(Path, "mkdir", _explode)
    recorder = OutputRecorder(tmp_path, preview_chars=100)

    bounded = recorder.record("stdout", "x" * 5000)

    assert bounded.pointer is None
    assert bounded.truncated
    assert bounded.text


def test_the_spill_directory_is_harness_scratch_not_a_guarantee() -> None:
    """Landlock only adds access; protecting scratch would make every
    workspace inexpressible."""
    assert SPILL_DIRECTORY.split("/")[0] == HARNESS_METADATA_NAME
    assert HARNESS_METADATA_NAME not in PROTECTED_METADATA_NAMES
    assert HARNESS_METADATA_NAME in METADATA_NAMES


def test_listing_files_omits_harness_metadata(tmp_path: Path) -> None:
    session = WorkspaceSession(tmp_path)
    (tmp_path / "analysis.py").write_text("pass")
    OutputRecorder(session.root, preview_chars=50).record("stdout", "y" * 500)

    payload = _content(
        asyncio.run(
            WorkspaceToolProvider(session).execute_tool_call(
                _workspace_output_call(LIST_FILES)
            )
        )
    )
    assert payload["files"] == ["analysis.py"]


def test_a_symlinked_metadata_directory_does_not_redirect_the_spill(
    tmp_path: Path,
) -> None:
    """Bubblewrap skips absent read-only bind paths; host-side spills must
    resist later symlinks."""
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (root / SPILL_DIRECTORY.split("/")[0]).symlink_to(outside)

    bounded = OutputRecorder(root, preview_chars=50).record(
        "stdout", "x" * 5000
    )

    assert bounded.pointer is None
    # Even mkdir would let command-chosen paths cause a host-side write.
    assert list(outside.rglob("*")) == []


def test_a_session_creates_the_metadata_directory_up_front(
    tmp_path: Path,
) -> None:
    session = WorkspaceSession(tmp_path)
    assert (session.root / SPILL_DIRECTORY).is_dir()


def test_a_truncated_read_hands_back_a_way_to_the_rest(
    tmp_path: Path,
) -> None:
    session = WorkspaceSession(tmp_path)
    (tmp_path / "big.txt").write_text("y" * 40_000)

    payload = _content(
        asyncio.run(
            WorkspaceToolProvider(session).execute_tool_call(
                _workspace_output_call(
                    READ_FILE, json.dumps({"path": "big.txt"})
                )
            )
        )
    )

    assert payload["truncated"] is True
    assert payload["full_output"].startswith(SPILL_DIRECTORY)
