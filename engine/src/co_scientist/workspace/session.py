"""A run's workspace: the surface an agent actually calls.

Binds the pieces that are individually inert -- a confinement policy, a
command classifier, a patch applier -- to one directory belonging to one
run, so that every operation is confined to that directory by
construction rather than by each caller remembering to pass a root.

Two design notes worth stating, because both are easy to get backwards.

**The session is not the boundary.** It is a convenience over the
boundary. `policy` is what confines; a bug here can at worst run a
command the sandbox then refuses. Nothing in this module should ever be
the only thing standing between model-authored code and the filesystem.

**Effects are declared, not inferred.** Each tool exposes the effect
vocabulary from `tool_effects`, so the loop that dispatches them already
knows a command execution is a barrier and must not run beside anything
else. Declaring them here rather than at the registration site keeps the
declaration next to the behaviour it describes.
"""

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
from co_scientist.sandbox.policy import SandboxPolicy, campaign_workspace_policy
from co_scientist.sandbox.runner import _terminate, build_env
from co_scientist.tool_effects import ToolEffect
from co_scientist.workspace.output import SPILL_DIRECTORY

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


# Default ceiling for one command. Long enough for a real analysis step,
# short enough that a hung process does not hold a durable task's lease
# past its renewal.
DEFAULT_COMMAND_TIMEOUT_SECONDS = 300.0


def _ensure_metadata_directory(root: Path) -> None:
    """Creates the harness's metadata directory before any command runs.

    Not a convenience -- it closes a real escape on Linux. bwrap's
    ``--ro-bind-try`` *skips* a path that does not exist, so on a fresh
    workspace ``.cosci`` is an ordinary writable location and the first
    confined command can replace it with a symlink to anywhere. The
    recorder then spills through that symlink from *this* process, which
    is outside the sandbox: attacker-influenced bytes, attacker-chosen
    directory, host privileges.

    Creating it up front means the try-bind binds from command one.
    macOS cannot show this -- seatbelt's deny rule matches the path
    whether or not it exists -- so it is Linux, which is production, that
    was exposed. Same shape as the tmpfs escape: a protection present in
    the source that does not bind at run time.
    """
    try:
        (root / SPILL_DIRECTORY).mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - filesystem-dependent
        logger.warning("could not create the workspace metadata dir: %s", exc)


def _is_metadata(relative: Path) -> bool:
    """Reports whether a workspace-relative path is harness metadata."""
    return any(part in METADATA_NAMES for part in relative.parts)


@dataclass(frozen=True)
class CommandOutcome:
    """What running one command produced, including why it was allowed.

    Attributes:
        result: The process outcome.
        required_approval: Whether the command fell outside the
            read-only allowlist. Recorded rather than merely acted on,
            so an audit can answer "what did this run execute that a
            human would have been asked about".
    """

    result: ExecResult
    required_approval: bool


@dataclass(frozen=True)
class PatchOutcome:
    """What applying a patch produced.

    Attributes:
        changed: Paths written, relative to the workspace root.
        rungs: Per-path record of how exactly each hunk matched, so an
            edit that only applied after whitespace folding is visible
            rather than silent.
    """

    changed: tuple[str, ...]
    rungs: dict[str, tuple[str, ...]]


class WorkspaceSession:
    """One run's confined working directory.

    Attributes:
        root: The directory every operation is confined to.
        policy: The confinement applied to commands run here.
        skills_enabled: Whether the vendored science skills are offered
            to the model working here. Off by default and decided per
            consumer rather than by the installation: two agents have
            been measured on the same bundle with opposite outcomes, so
            installing the skills must not be what turns them on. See
            ``skills/catalog.py``.
    """

    # Effect declarations for the tools this session exposes, in the
    # vocabulary tool_effects defines. run_command is PROCESS and
    # apply_patch is WRITE, so both are barriers and neither will run
    # concurrently with a sibling tool call.
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
        """Binds a session to a directory.

        Args:
            root: The workspace directory. Created if absent, because a
                run's first action should not have to be mkdir.
            policy: Confinement override. Defaults to write access to
                the workspace and nothing else.
            network_allowed: Whether commands may reach the network.
                Ignored when ``policy`` is given explicitly.
            skills_enabled: Whether to offer the vendored science skills
                here. Requires network access to be of any use.
        """
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve()
        _ensure_metadata_directory(self.root)
        self.policy = campaign_workspace_policy(
            policy
            or workspace_write(self.root, network_allowed=network_allowed)
        )
        self.skills_enabled = skills_enabled
        # Commands that outlive the call that started them. Lazily
        # populated: a workspace used only for patches never starts one.
        self.sessions = SessionRegistry()

    async def run_command(
        self,
        argv: list[str],
        *,
        timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
        env_extra: dict[str, str] | None = None,
    ) -> CommandOutcome:
        """Runs a command confined to this workspace.

        Args:
            argv: The command, already split. Never a shell string --
                this path does no shell parsing, so a caller wanting a
                pipeline asks for a shell explicitly.
            timeout_seconds: Wall-clock ceiling.
            env_extra: Values to add to the rebuilt environment. The
                host's own environment is never inherited.

        Returns:
            The outcome, including whether the command was outside the
            read-only allowlist.
        """
        from co_scientist.sandbox.runner import build_env

        needs_approval = not is_known_safe(argv)
        # The sandbox mounts no private /tmp (see sandbox/bwrap.py), so
        # scratch space has to be somewhere the policy actually grants.
        # The workspace is the one such place, and pointing TMPDIR at it
        # keeps temp files with the run that made them.
        env = {"TMPDIR": str(self.root), **(env_extra or {})}
        result = await run_sandboxed(
            ExecRequest(
                argv=argv,
                policy=campaign_workspace_policy(self.policy),
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
        """Ends every command still running in this workspace.

        A session outlives the call that started it by design, so
        nothing else ends one that the model never killed. Sessions are
        process-local, which bounds the leak at the worker's own
        lifetime -- but a caller that keeps one process alive across
        many workspaces has to call this. The simulation review does,
        in a ``finally`` around its tool loop
        (``agents/reflection/simulation_execution``). See the module
        docstring in ``command_session`` for why the reaper belongs to
        the caller rather than here.
        """
        await self.sessions.close()

    def apply_patch_text(self, patch_text: str) -> PatchOutcome:
        """Applies a V4A patch envelope inside this workspace.

        Args:
            patch_text: The full envelope.

        Returns:
            What changed.

        Raises:
            PatchError: If the envelope is malformed or any hunk's
                context does not match. Nothing is written in that case.
        """
        result = apply_patch(parse_patch(patch_text), self.root)
        return PatchOutcome(changed=result.changed, rungs=result.rungs)

    def write_file(self, relative: str, content: str) -> None:
        """Writes one whole file into the workspace, creating parents.

        The model's most common intent in a simulation is "here is the
        program I want to run". Expressing that as a context-anchored
        patch is the wrong shape for it: there is no context to anchor
        to in a new file, so the whole envelope is ceremony, and getting
        the ceremony wrong costs a turn. Measured on a real simulation,
        33 of one loop's tool results were ``apply_patch`` rejections
        over exactly that -- the model never got its program written and
        spent the turn budget on the format. ``apply_patch`` remains the
        right tool for *editing* a file, where the context anchoring is
        the point.

        Args:
            relative: Path relative to the workspace root.
            content: The file's full text, replacing anything there.

        Raises:
            PatchError: If the path escapes the workspace. Reusing the
                patch error type keeps one containment message for the
                model to act on, whichever operation tripped it.
        """
        target = self.resolve_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def read_file(self, relative: str, max_bytes: int = 200_000) -> str:
        """Reads a file from the workspace.

        Args:
            relative: Path relative to the workspace root.
            max_bytes: Ceiling on returned content.

        Returns:
            The file's text, truncated at the ceiling.

        Raises:
            PatchError: If the path escapes the workspace. Reusing the
                patch error type keeps one containment message for the
                model to act on, whichever operation tripped it.
        """
        target = self.resolve_path(relative)
        if not target.is_file():
            raise PatchError(f"no such file in workspace: {relative!r}")
        raw = target.read_bytes()[:max_bytes]
        return raw.decode("utf-8", errors="replace")

    def list_files(self) -> tuple[str, ...]:
        """Lists the workspace's files, relative to its root.

        Protected metadata directories are omitted. They hold the
        harness's own records -- spilled command output, snapshot state
        -- and listing them among the work invites the model to treat
        its own transcript as an input.
        """
        return tuple(
            sorted(
                str(relative)
                for path in self.root.rglob("*")
                if path.is_file()
                and not _is_metadata(relative := path.relative_to(self.root))
            )
        )

    def resolve_path(self, relative: str) -> Path:
        """Resolves a workspace-relative path, refusing any escape.

        Public because callers that are not the tool surface need it --
        the evaluator writes a variant's source and reads its metrics
        file, and doing that with a bare ``root / relative`` would skip
        the containment check the tools get for free.

        Args:
            relative: Path relative to the workspace root.

        Returns:
            The absolute path.

        Raises:
            PatchError: If the path resolves outside the workspace.
        """
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise PatchError(
                f"path {relative!r} resolves outside the workspace"
            )
        return candidate
