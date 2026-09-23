"""Commands that outlive one tool call.

A bounded `run_command` has one answer for a command still running at
its deadline: kill it and report a timeout. That is right for an
evaluation stage, where the caller must return a *score* and an
unbounded stage would hold a worker forever. It is wrong for an agent at
a terminal, where the long command is the normal case -- a build, a test
suite, a training run -- and where killing it discards the work and,
worse, discards the output it had already produced (`sandbox.runner`
drops both streams on the timeout path, because a killed
`communicate()` has nothing to hand back).

So a command started here keeps running and the caller gets a session
id. **"Still running" is a successful return, not an error.** Output
accumulates into the session as it arrives, and each read takes what is
new since a cursor, so polling twice does not repeat a line and a
command producing megabytes does not have to be re-read from the start.

Three limits are deliberate and one is a consequence.

**Sessions are process-local.** The child belongs to this process; a
worker that dies takes its sessions with it. Making one survive a
restart means a supervisor outside the worker, which is a deployment
change, not a code change. What matters is that the loss is *legible*
rather than silent: a resumed turn carries a tool call whose result
never arrived, which `llm_tool_transcript` turns into an explicit
aborted result rather than an invalid conversation.

**Output is capped per stream** and marked when it is cut, because a
runaway command writing an infinite stream would otherwise be a memory
leak with a session id.

**There is a ceiling on live sessions**, since each one is a process
this workspace is responsible for ending.

The consequence: `close()` is not optional. A session left running when
its workspace goes away is an orphan holding a sandbox open.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from co_scientist.sandbox.argv import wrap_argv
from co_scientist.sandbox.policy import SandboxPolicy, campaign_workspace_policy
from co_scientist.sandbox.runner import _terminate, build_env

logger = logging.getLogger(__name__)

# Most bytes kept per stream per session. Past this the tail is dropped
# and the session reports itself truncated: the alternative is a command
# printing forever being a memory leak that looks like progress.
MAX_SESSION_OUTPUT_BYTES = 1_000_000

# Most commands one workspace may have in flight. Each is a live process
# this workspace has to end, so an unbounded count is an unbounded
# number of orphans after one bad turn.
MAX_LIVE_SESSIONS = 4


@dataclass
class _Stream:
    """One captured stream and how much of it a reader has seen."""

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
        """Returns text written after ``cursor``, and the new cursor."""
        start = max(0, min(cursor, len(self.data)))
        return (
            bytes(self.data[start:]).decode("utf-8", errors="replace"),
            len(self.data),
        )


@dataclass
class SessionRead:
    """What a caller learns from one look at a session.

    Attributes:
        session_id: The session this describes.
        running: Whether the command is still going. True is a normal,
            successful answer -- the caller polls again rather than
            treating it as a failure.
        exit_code: Set once it has finished.
        stdout: Output written since the caller's cursor, not from the
            start, so polling a chatty command does not re-read it.
        stderr: The same for the error stream.
        cursor: What to pass next time.
        truncated: Per stream, whether output was dropped at the cap.
    """

    session_id: str
    running: bool
    exit_code: int | None
    stdout: str
    stderr: str
    cursor: dict[str, int]
    truncated: dict[str, bool]


class CommandSession:
    """One confined command, running past the call that started it."""

    def __init__(self, session_id: str, argv: list[str]) -> None:
        """Binds a session to its id and the command it will run."""
        self.id = session_id
        self.argv = list(argv)
        self._out = _Stream()
        self._err = _Stream()
        self._proc: asyncio.subprocess.Process | None = None
        self._pumps: list[asyncio.Task[None]] = []

    @property
    def running(self) -> bool:
        """Whether the command has yet to exit."""
        return self._proc is not None and self._proc.returncode is None

    @property
    def exit_code(self) -> int | None:
        """The command's status, or None while it is still running."""
        return self._proc.returncode if self._proc is not None else None

    async def start(
        self,
        *,
        policy: SandboxPolicy,
        cwd: Path,
        env: dict[str, str],
    ) -> None:
        """Launches the command under confinement.

        Raises:
            UnsupportedSandboxError: If this platform cannot confine the
                policy. Raised rather than degrading, as everywhere else
                a command is launched.
        """
        self._proc = await asyncio.create_subprocess_exec(
            *wrap_argv(self.argv, campaign_workspace_policy(policy)),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=env,
            # Its own group, so ending it ends the tree it spawned.
            start_new_session=True,
        )
        self._pumps = [
            asyncio.create_task(self._pump(self._proc.stdout, self._out)),
            asyncio.create_task(self._pump(self._proc.stderr, self._err)),
        ]

    async def _pump(self, reader: object, into: _Stream) -> None:
        """Drains one stream into the session as it arrives.

        Reading continuously rather than at poll time is what makes the
        output survive: a pipe nobody reads fills and blocks the writer,
        so a command producing more than a pipe buffer would hang
        waiting for a reader that only shows up between polls.
        """
        stream = reader
        while True:
            chunk = await stream.read(8192)  # type: ignore[attr-defined]
            if not chunk:
                return
            into.append(chunk)

    async def wait_for(self, seconds: float) -> None:
        """Waits up to ``seconds`` for the command to finish."""
        if self._proc is None:
            return
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return
        await asyncio.gather(*self._pumps, return_exceptions=True)

    def read(self, cursor: dict[str, int] | None = None) -> SessionRead:
        """Takes everything written since ``cursor``."""
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
        """Sends input to the running command.

        Raises:
            ValueError: If the command has already exited. Silently
                discarding the input would leave a model believing it
                had answered a prompt that nothing read.
        """
        if self._proc is None or self._proc.stdin is None or not self.running:
            raise ValueError(f"session {self.id} is not accepting input")
        self._proc.stdin.write(text.encode("utf-8"))
        await self._proc.stdin.drain()

    async def close(self) -> None:
        """Ends the command and its children, if it is still running."""
        if self._proc is not None:
            await _terminate(self._proc)
        for pump in self._pumps:
            pump.cancel()
        await asyncio.gather(*self._pumps, return_exceptions=True)


class SessionRegistry:
    """The live command sessions belonging to one workspace."""

    def __init__(self) -> None:
        """Starts with no sessions."""
        self._sessions: dict[str, CommandSession] = {}

    def get(self, session_id: str) -> CommandSession:
        """Returns a session by id.

        Raises:
            KeyError: If no such session exists here.
        """
        return self._sessions[session_id]

    async def start(
        self,
        argv: list[str],
        *,
        policy: SandboxPolicy,
        cwd: Path,
        env_extra: dict[str, str] | None = None,
    ) -> CommandSession:
        """Starts a command and keeps it.

        Raises:
            RuntimeError: If too many commands are already in flight.
                Refused rather than queued: a caller told "started" for
                something that has not started cannot poll it.
        """
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
        """How many commands are actually still running."""
        return sum(1 for s in self._sessions.values() if s.running)

    def _make_room(self) -> None:
        """Forgets the oldest finished sessions, keeping the recent ones.

        A finished session is still how its exit code and last lines are
        reported, so it is kept rather than dropped the moment it exits;
        the ceiling is on how many are *running*, and this only stops
        the record growing without bound.
        """
        finished = [k for k, s in self._sessions.items() if not s.running]
        for key in finished[: max(0, len(finished) - MAX_LIVE_SESSIONS)]:
            del self._sessions[key]

    async def close(self) -> None:
        """Ends every session this workspace still holds."""
        for session in list(self._sessions.values()):
            await session.close()
        self._sessions.clear()
