"""OS policy enforces the boundary; sessions coordinate operations."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from co_scientist.patch import PatchError, apply_patch, parse_patch
from co_scientist.sandbox import (
    METADATA_NAMES,
    ExecRequest,
    ExecResult,
    is_known_safe,
    run_sandboxed,
    workspace_write,
)
from co_scientist.sandbox.argv import wrap_argv
from co_scientist.sandbox.policy import SandboxPolicy
from co_scientist.sandbox.runner import _terminate, build_env
from co_scientist.tool_effects import ToolEffect
from co_scientist.workspace.output import SPILL_DIRECTORY

logger = logging.getLogger(__name__)


# Bound each captured stream so endless output cannot become a memory leak.
MAX_SESSION_OUTPUT_BYTES = 1_000_000

# Bound live processes so a bad turn cannot leave unlimited orphans.
MAX_LIVE_SESSIONS = 4


@dataclass
class _Stream:
    data: bytearray = field(default_factory=bytearray)
    truncated: bool = False

    def append(self, chunk: bytes) -> None:
        room = MAX_SESSION_OUTPUT_BYTES - len(self.data)
        if room <= 0:
            self.truncated = True
            return
        if len(chunk) > room:
            self.truncated = True
        self.data.extend(chunk[:room])

    def since(self, cursor: int) -> tuple[str, int]:
        start = max(0, min(cursor, len(self.data)))
        return (
            bytes(self.data[start:]).decode("utf-8", errors="replace"),
            len(self.data),
        )


@dataclass
class SessionRead:
    session_id: str
    running: bool
    exit_code: int | None
    stdout: str
    stderr: str
    cursor: dict[str, int]
    truncated: dict[str, bool]


class CommandSession:
    def __init__(self, session_id: str, argv: list[str]) -> None:
        self.id = session_id
        self.argv = list(argv)
        self._out = _Stream()
        self._err = _Stream()
        self._proc: asyncio.subprocess.Process | None = None
        self._pumps: list[asyncio.Task[None]] = []

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    @property
    def exit_code(self) -> int | None:
        return self._proc.returncode if self._proc is not None else None

    async def start(
        self,
        *,
        policy: SandboxPolicy,
        cwd: Path,
        env: dict[str, str],
    ) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *wrap_argv(self.argv, policy),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=env,
            # A separate process group makes cancellation end the entire tree.
            start_new_session=True,
        )
        self._pumps = [
            asyncio.create_task(self._pump(self._proc.stdout, self._out)),
            asyncio.create_task(self._pump(self._proc.stderr, self._err)),
        ]

    async def _pump(self, reader: object, into: _Stream) -> None:
        """Drain continuously: a full unread pipe blocks the writer between
        polls.
        """
        stream = reader
        while True:
            chunk = await stream.read(8192)  # type: ignore[attr-defined]
            if not chunk:
                return
            into.append(chunk)

    async def wait_for(self, seconds: float) -> None:
        if self._proc is None:
            return
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return
        await asyncio.gather(*self._pumps, return_exceptions=True)

    def read(self, cursor: dict[str, int] | None = None) -> SessionRead:
        marks = cursor or {}
        stdout, out_at = self._out.since(int(marks.get("stdout", 0)))
        stderr, err_at = self._err.since(int(marks.get("stderr", 0)))
        return SessionRead(
            session_id=self.id,
            running=self.running,
            exit_code=self.exit_code,
            stdout=stdout,
            stderr=stderr,
            cursor={"stdout": out_at, "stderr": err_at},
            truncated={
                "stdout": self._out.truncated,
                "stderr": self._err.truncated,
            },
        )

    async def write(self, text: str) -> None:
        """Silently discarding input would claim a prompt was answered after
        the process exited.
        """
        if self._proc is None or self._proc.stdin is None or not self.running:
            raise ValueError(f"session {self.id} is not accepting input")
        self._proc.stdin.write(text.encode("utf-8"))
        await self._proc.stdin.drain()

    async def close(self) -> None:
        """Sessions outlive their starting calls; callers must reap them when a
        workspace closes.
        """
        if self._proc is not None:
            await _terminate(self._proc)
        for pump in self._pumps:
            pump.cancel()
        await asyncio.gather(*self._pumps, return_exceptions=True)


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, CommandSession] = {}

    def get(self, session_id: str) -> CommandSession:
        return self._sessions[session_id]

    async def start(
        self,
        argv: list[str],
        *,
        policy: SandboxPolicy,
        cwd: Path,
        env_extra: dict[str, str] | None = None,
    ) -> CommandSession:
        self._make_room()
        if self._live_count() >= MAX_LIVE_SESSIONS:
            raise RuntimeError(
                f"{MAX_LIVE_SESSIONS} commands are already running here; "
                f"wait for one to finish or end it first"
            )
        session = CommandSession(str(uuid.uuid4()), argv)
        await session.start(
            policy=policy,
            cwd=cwd,
            env=build_env(extra={"TMPDIR": str(cwd), **(env_extra or {})}),
        )
        self._sessions[session.id] = session
        return session

    def _live_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.running)

    def _make_room(self) -> None:
        """Retain finished exit status and final output while bounding process-
        local session history.
        """
        finished = [k for k, s in self._sessions.items() if not s.running]
        for key in finished[: max(0, len(finished) - MAX_LIVE_SESSIONS)]:
            del self._sessions[key]

    async def close(self) -> None:
        """Sessions outlive their starting calls; callers must reap them when a
        workspace closes.
        """
        for session in list(self._sessions.values()):
            await session.close()
        self._sessions.clear()


# Bound commands so hangs cannot outlive durable lease renewal.
DEFAULT_COMMAND_TIMEOUT_SECONDS = 300.0


def _ensure_metadata_directory(root: Path) -> None:
    """Create metadata before commands can symlink it."""
    try:
        (root / SPILL_DIRECTORY).mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - filesystem-dependent
        logger.warning("could not create the workspace metadata dir: %s", exc)


def _is_metadata(relative: Path) -> bool:
    return any(part in METADATA_NAMES for part in relative.parts)


@dataclass(frozen=True)
class CommandOutcome:
    result: ExecResult
    required_approval: bool


@dataclass(frozen=True)
class PatchOutcome:
    changed: tuple[str, ...]
    rungs: dict[str, tuple[str, ...]]


class WorkspaceSession:
    """Skills are enabled per consumer, never merely by installation; measured
    effects differ by agent.
    """

    # PROCESS/WRITE effects are barriers; declare them beside operations before
    # registration.
    RUN_COMMAND_EFFECTS = ToolEffect.PROCESS | ToolEffect.READ
    APPLY_PATCH_EFFECTS = ToolEffect.WRITE | ToolEffect.READ
    READ_FILE_EFFECTS = ToolEffect.READ
    WRITE_FILE_EFFECTS = ToolEffect.WRITE | ToolEffect.READ

    def __init__(
        self,
        root: Path,
        *,
        policy: SandboxPolicy | None = None,
        network_allowed: bool = False,
        skills_enabled: bool = False,
    ) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve()
        _ensure_metadata_directory(self.root)
        self.policy = policy or workspace_write(self.root, network_allowed=network_allowed)
        self.skills_enabled = skills_enabled
        self.sessions = SessionRegistry()

    async def run_command(
        self,
        argv: list[str],
        *,
        timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
        env_extra: dict[str, str] | None = None,
    ) -> CommandOutcome:
        from co_scientist.sandbox.runner import build_env

        needs_approval = not is_known_safe(argv)
        # No private /tmp is mounted; point TMPDIR inside the granted workspace.
        env = {"TMPDIR": str(self.root), **(env_extra or {})}
        result = await run_sandboxed(
            ExecRequest(
                argv=argv,
                policy=self.policy,
                cwd=self.root,
                timeout_seconds=timeout_seconds,
                env=build_env(extra=env),
            )
        )
        logger.debug(
            "workspace command %s exited %s (approval_required=%s)",
            argv[0],
            result.exit_code,
            needs_approval,
        )
        return CommandOutcome(result=result, required_approval=needs_approval)

    async def close(self) -> None:
        """Sessions outlive their starting calls; callers must reap them when a
        workspace closes.
        """
        await self.sessions.close()

    def apply_patch_text(self, patch_text: str) -> PatchOutcome:
        result = apply_patch(parse_patch(patch_text), self.root)
        return PatchOutcome(changed=result.changed, rungs=result.rungs)

    def write_file(self, relative: str, content: str) -> None:
        """Whole-file creation avoids context-patch failures on a new program;
        patches retain edit anchoring.
        """
        target = self.resolve_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def read_file(self, relative: str, max_bytes: int = 200_000) -> str:
        target = self.resolve_path(relative)
        if not target.is_file():
            raise PatchError(f"no such file in workspace: {relative!r}")
        raw = target.read_bytes()[:max_bytes]
        return raw.decode("utf-8", errors="replace")

    def list_files(self) -> tuple[str, ...]:
        """Exclude harness metadata so the model cannot treat its own
        transcript as research input.
        """
        return tuple(
            sorted(
                str(relative)
                for path in self.root.rglob("*")
                if path.is_file() and not _is_metadata(relative := path.relative_to(self.root))
            )
        )

    def resolve_path(self, relative: str) -> Path:
        """Non-tool callers must receive the same containment check as tool
        operations.
        """
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise PatchError(f"path {relative!r} resolves outside the workspace")
        return candidate
