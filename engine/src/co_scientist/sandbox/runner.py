"""Running a confined command, and stopping it when it will not stop.

Three things here are not conveniences.

**The kill is real.** A timeout escalates SIGTERM to SIGKILL against the
whole process *group*, not the direct child. OpenEvolve times out with
``asyncio.wait_for`` over a thread-pool executor, which cannot kill
anything -- the future is abandoned and the runaway program keeps
burning CPU for the rest of the run. A command that spawns children and
exits leaves those children holding the pipe, so killing only the child
hangs the read instead of ending it.

**The environment is rebuilt, not inherited.** Everything the host
process holds -- provider keys, database paths, cloud credentials -- is
absent unless a caller names it. Confining the filesystem while handing
over ``os.environ`` would leave the most valuable thing in the process
sitting in plain view of the code being confined.

**Output is bounded.** A confined program can emit output faster than
anything reads it; an unbounded read turns a stray ``print`` in a loop
into the harness running out of memory.

What this deliberately does *not* provide is memory, CPU, and pid
limits. Those belong to the container the exec service runs in, where
they are a few flags and are enforced by the kernel against everything
inside. Approximating them here would mean ``preexec_fn``, which forks
with the parent's locks held -- and this host runs worker cohorts on
several threads, so that is a deadlock waiting for a busy moment. See
docs: resource limits are the container's job.
"""

import asyncio
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path

from co_scientist.sandbox.argv import wrap_argv
from co_scientist.sandbox.policy import SandboxPolicy

logger = logging.getLogger(__name__)

# Variables a confined command may keep. PATH so it can find binaries,
# HOME because many runtimes fail outright without one, and the locale
# and temp-dir vars because their absence produces encoding bugs that
# look like data corruption. Everything else must be named per call.
DEFAULT_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TZ",
)

# Grace between asking a command to stop and making it stop.
_SIGTERM_GRACE_SECONDS = 5.0

# Default ceiling on captured output per stream.
DEFAULT_MAX_OUTPUT_BYTES = 1_000_000


@dataclass(frozen=True)
class ExecResult:
    """The outcome of one confined command.

    Attributes:
        exit_code: The process exit status; None if it was killed before
            reporting one.
        stdout: Captured standard output, truncated to the byte ceiling.
        stderr: Captured standard error, truncated to the byte ceiling.
        timed_out: Whether the command was killed for exceeding its
            deadline. Distinguished from a non-zero exit because they
            mean different things to a caller deciding whether to retry.
        truncated: Whether either stream hit the ceiling.
    """

    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    truncated: bool = False

    @property
    def ok(self) -> bool:
        """Whether the command completed successfully."""
        return self.exit_code == 0 and not self.timed_out


def build_env(
    allowlist: tuple[str, ...] = DEFAULT_ENV_ALLOWLIST,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Builds a confined command's environment from scratch.

    Args:
        allowlist: Names to copy from the host environment when present.
        extra: Explicit values to add, overriding anything copied. This
            is how a caller passes a credential the command genuinely
            needs -- deliberately per call, never ambient.

    Returns:
        A fresh environment mapping. Nothing not named here is present.
    """
    env = {name: os.environ[name] for name in allowlist if name in os.environ}
    if extra:
        env.update(extra)
    return env


def _decode(raw: bytes, limit: int) -> tuple[str, bool]:
    """Decodes captured output, truncating at the byte ceiling."""
    truncated = len(raw) > limit
    body = raw[:limit] if truncated else raw
    return body.decode("utf-8", errors="replace"), truncated


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """Ends a process group, escalating to SIGKILL if it does not stop.

    Signals the group rather than the process: a command that spawned
    children and exited leaves them holding the pipe, so killing only
    the direct child hangs the read instead of ending it.
    """
    if proc.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return

    try:
        await asyncio.wait_for(proc.wait(), timeout=_SIGTERM_GRACE_SECONDS)
        return
    except asyncio.TimeoutError:
        logger.warning(
            "confined command %s ignored SIGTERM; sending SIGKILL", proc.pid
        )

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return
    await proc.wait()


@dataclass(frozen=True)
class ExecRequest:
    """What to run, under what policy, and within what bounds.

    Attributes:
        argv: The command, already split. Never a shell string: this
            path does no shell parsing, so a caller wanting a pipeline
            must ask for a shell explicitly and accept what that means.
        policy: The confinement decision.
        cwd: Working directory for the command.
        timeout_seconds: Wall-clock ceiling; None for no deadline.
        env: The complete environment. Defaults to the allowlist.
        max_output_bytes: Per-stream capture ceiling.
    """

    argv: list[str]
    policy: SandboxPolicy
    cwd: Path | None = None
    timeout_seconds: float | None = 300.0
    env: dict[str, str] | None = None
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES


async def run_sandboxed(request: ExecRequest) -> ExecResult:
    """Runs a command under confinement and returns its outcome.

    Args:
        request: What to run and the bounds to run it within.

    Returns:
        The command's outcome. A timeout is reported as
        ``timed_out=True`` rather than raising, because a caller that
        must return a *scored* result -- an evaluation task, where
        raising costs a retry budget -- needs the distinction as data.

    Raises:
        ValueError: If the command is empty.
        UnsupportedSandboxError: If this platform cannot confine the
            policy. Raised rather than degrading: see sandbox.argv.
    """
    wrapped = wrap_argv(request.argv, request.policy)
    env = request.env if request.env is not None else build_env()

    proc = await asyncio.create_subprocess_exec(
        *wrapped,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(request.cwd) if request.cwd else None,
        env=env,
        # Its own process group, so a timeout can end the whole tree.
        start_new_session=True,
    )

    return await _collect(proc, request)


async def _collect(
    proc: asyncio.subprocess.Process, request: ExecRequest
) -> ExecResult:
    """Awaits a running command's output within its deadline."""
    timed_out = False
    try:
        raw_out, raw_err = await asyncio.wait_for(
            proc.communicate(), timeout=request.timeout_seconds
        )
    except asyncio.TimeoutError:
        timed_out = True
        await _terminate(proc)
        raw_out, raw_err = b"", b""
        logger.warning(
            "confined command timed out after %ss: %s",
            request.timeout_seconds,
            request.argv[0],
        )

    stdout, out_cut = _decode(raw_out or b"", request.max_output_bytes)
    stderr, err_cut = _decode(raw_err or b"", request.max_output_bytes)
    return ExecResult(
        exit_code=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        truncated=out_cut or err_cut,
    )
