"""Tests for running confined commands.

As in test_sandbox.py, the tests that matter spawn real processes. A
timeout test that only checks a flag would pass against an
implementation that abandons the process and lets it keep running, which
is precisely the bug being avoided -- so the timeout tests assert the
process is *gone*, not merely that we stopped waiting for it.
"""

import os
import signal
import sys
import time
from pathlib import Path

import pytest

from co_scientist.sandbox.policy import SandboxKind, SandboxPolicy
from co_scientist.sandbox.runner import (
    DEFAULT_ENV_ALLOWLIST,
    ExecRequest,
    ExecResult,
    build_env,
    run_sandboxed,
)

_UNCONFINED = SandboxPolicy(kind=SandboxKind.DANGER_FULL_ACCESS)

_requires_posix = pytest.mark.skipif(
    sys.platform == "win32", reason="process-group signalling is POSIX-only"
)


# --- environment ----------------------------------------------------------


def test_env_is_built_from_scratch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A secret in the host environment must not reach the command."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = build_env()

    assert "DEEPSEEK_API_KEY" not in env
    assert env["PATH"] == "/usr/bin"


def test_named_extras_are_added(monkeypatch: pytest.MonkeyPatch) -> None:
    """A credential the command genuinely needs is passed per call."""
    monkeypatch.setenv("PATH", "/usr/bin")
    env = build_env(extra={"SOME_TOKEN": "value"})
    assert env["SOME_TOKEN"] == "value"


def test_allowlist_covers_what_runtimes_break_without() -> None:
    for name in ("PATH", "HOME", "TMPDIR"):
        assert name in DEFAULT_ENV_ALLOWLIST


@pytest.mark.asyncio
async def test_the_host_environment_does_not_leak_into_the_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: the secret is absent from the command's own view."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret")

    result = await run_sandboxed(
        ExecRequest(
            argv=["/usr/bin/env"], policy=_UNCONFINED, timeout_seconds=30
        )
    )

    assert result.ok, result.stderr
    assert "sk-secret" not in result.stdout


# --- outcomes -------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_successful_command_reports_its_output() -> None:
    result = await run_sandboxed(
        ExecRequest(
            argv=["/bin/echo", "hello"],
            policy=_UNCONFINED,
            timeout_seconds=30,
        )
    )
    assert result.ok
    assert result.stdout.strip() == "hello"


@pytest.mark.asyncio
async def test_a_failing_command_is_not_a_timeout() -> None:
    """Non-zero and timed-out mean different things to a retry decision."""
    result = await run_sandboxed(
        ExecRequest(
            argv=["/bin/sh", "-c", "exit 3"],
            policy=_UNCONFINED,
            timeout_seconds=30,
        )
    )
    assert result.exit_code == 3
    assert not result.timed_out
    assert not result.ok


@pytest.mark.asyncio
async def test_output_is_truncated_at_the_ceiling() -> None:
    result = await run_sandboxed(
        ExecRequest(
            argv=["/bin/sh", "-c", "printf 'x%.0s' $(seq 1 5000)"],
            policy=_UNCONFINED,
            timeout_seconds=30,
            max_output_bytes=100,
        )
    )
    assert result.truncated
    assert len(result.stdout) == 100


@pytest.mark.asyncio
async def test_runner_refuses_an_empty_command() -> None:
    with pytest.raises(ValueError, match="empty command"):
        await run_sandboxed(ExecRequest(argv=[], policy=_UNCONFINED))


# --- the kill -------------------------------------------------------------


@_requires_posix
@pytest.mark.asyncio
async def test_a_timeout_reports_rather_than_raises() -> None:
    """An evaluation task must be able to record a scored failure."""
    result = await run_sandboxed(
        ExecRequest(
            argv=["/bin/sleep", "30"],
            policy=_UNCONFINED,
            timeout_seconds=0.5,
        )
    )
    assert isinstance(result, ExecResult)
    assert result.timed_out
    assert not result.ok


def _pid_alive(pid: int) -> bool:
    """Reports whether a pid still exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@_requires_posix
@pytest.mark.asyncio
async def test_a_timed_out_command_is_actually_dead(tmp_path: Path) -> None:
    """The load-bearing timeout test.

    An implementation that merely stops awaiting would pass every other
    test in this file while the runaway process kept burning CPU for the
    rest of the run. This asserts the process is gone.
    """
    marker = tmp_path / "pid"
    script = (
        f"echo $$ > {marker}; "
        # Long enough that survival is unambiguous, quiet enough not to
        # produce output while it waits.
        "sleep 60"
    )

    result = await run_sandboxed(
        ExecRequest(
            argv=["/bin/sh", "-c", script],
            policy=_UNCONFINED,
            timeout_seconds=1.0,
        )
    )

    assert result.timed_out
    pid = int(marker.read_text().strip())
    # The kill is asynchronous at the OS level; give it a moment.
    for _ in range(50):
        if not _pid_alive(pid):
            break
        time.sleep(0.05)
    assert not _pid_alive(pid), f"process {pid} survived its timeout"


@_requires_posix
@pytest.mark.asyncio
async def test_orphaned_children_die_with_the_group(tmp_path: Path) -> None:
    """A grandchild must not outlive the timeout either.

    A command that spawns a child and exits leaves that child holding
    the pipe. Signalling only the direct child would leave this one
    running -- and, before the group kill, would hang the read instead
    of ending it.
    """
    marker = tmp_path / "child_pid"
    script = f"sh -c 'echo $$ > {marker}; sleep 60' & wait"

    result = await run_sandboxed(
        ExecRequest(
            argv=["/bin/sh", "-c", script],
            policy=_UNCONFINED,
            timeout_seconds=1.5,
        )
    )

    assert result.timed_out
    child_pid = int(marker.read_text().strip())
    for _ in range(50):
        if not _pid_alive(child_pid):
            break
        time.sleep(0.05)
    assert not _pid_alive(child_pid), (
        f"grandchild {child_pid} survived the group kill"
    )


@_requires_posix
@pytest.mark.asyncio
async def test_a_command_ignoring_sigterm_is_still_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SIGTERM is a request; the escalation is what makes it a deadline."""
    import co_scientist.sandbox.runner as runner_module

    # Shorten the grace so the test does not wait it out in real time.
    monkeypatch.setattr(runner_module, "_SIGTERM_GRACE_SECONDS", 0.5)

    marker = tmp_path / "stubborn_pid"
    script = f"trap '' {int(signal.SIGTERM)}; echo $$ > {marker}; sleep 60"

    result = await run_sandboxed(
        ExecRequest(
            argv=["/bin/sh", "-c", script],
            policy=_UNCONFINED,
            timeout_seconds=1.0,
        )
    )

    assert result.timed_out
    pid = int(marker.read_text().strip())
    for _ in range(60):
        if not _pid_alive(pid):
            break
        time.sleep(0.05)
    assert not _pid_alive(pid), f"process {pid} ignored SIGTERM and survived"
