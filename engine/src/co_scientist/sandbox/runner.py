"""Kill process groups and rebuild environments; captured output must remain
bounded. Container resource limits avoid threaded preexec_fn deadlocks.
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

# PATH/HOME/locale/temp variables support runtimes; credentials require explicit
# per-call injection.
DEFAULT_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TZ",
)

_SIGTERM_GRACE_SECONDS = 5.0

DEFAULT_MAX_OUTPUT_BYTES = 1_000_000


@dataclass(frozen=True)
class ExecResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def build_env(
    allowlist: tuple[str, ...] = DEFAULT_ENV_ALLOWLIST,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Never inherit provider/cloud credentials implicitly; callers name extra
    values per command.
    """
    env = {name: os.environ[name] for name in allowlist if name in os.environ}
    if extra:
        env.update(extra)
    return env


def _decode(raw: bytes, limit: int) -> tuple[str, bool]:
    truncated = len(raw) > limit
    body = raw[:limit] if truncated else raw
    return body.decode("utf-8", errors="replace"), truncated


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """Children can hold pipes after their parent exits; kill the group or
    output reads can hang.
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
    argv: list[str]
    policy: SandboxPolicy
    cwd: Path | None = None
    timeout_seconds: float | None = 300.0
    env: dict[str, str] | None = None
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES


async def run_sandboxed(request: ExecRequest) -> ExecResult:
    """Timeouts remain data so scored callers can distinguish them without
    spending a retry.
    """
    wrapped = wrap_argv(request.argv, request.policy)
    env = request.env if request.env is not None else build_env()

    proc = await asyncio.create_subprocess_exec(
        *wrapped,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(request.cwd) if request.cwd else None,
        env=env,
        # A separate process group lets timeout cleanup end the entire tree.
        start_new_session=True,
    )

    return await _collect(proc, request)


async def _collect(
    proc: asyncio.subprocess.Process, request: ExecRequest
) -> ExecResult:
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
