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

import logging
from dataclasses import dataclass
from pathlib import Path

from co_scientist.patch import PatchError, apply_patch, parse_patch
from co_scientist.sandbox import (
    PROTECTED_METADATA_NAMES,
    ExecRequest,
    ExecResult,
    SandboxPolicy,
    is_known_safe,
    run_sandboxed,
    workspace_write,
)
from co_scientist.tool_effects import ToolEffect
from co_scientist.workspace.output import SPILL_DIRECTORY

logger = logging.getLogger(__name__)

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
    return any(part in PROTECTED_METADATA_NAMES for part in relative.parts)


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
    """

    # Effect declarations for the tools this session exposes, in the
    # vocabulary tool_effects defines. run_command is PROCESS and
    # apply_patch is WRITE, so both are barriers and neither will run
    # concurrently with a sibling tool call.
    RUN_COMMAND_EFFECTS = ToolEffect.PROCESS | ToolEffect.READ
    APPLY_PATCH_EFFECTS = ToolEffect.WRITE | ToolEffect.READ
    READ_FILE_EFFECTS = ToolEffect.READ

    def __init__(
        self,
        root: Path,
        *,
        policy: SandboxPolicy | None = None,
        network_allowed: bool = False,
    ) -> None:
        """Binds a session to a directory.

        Args:
            root: The workspace directory. Created if absent, because a
                run's first action should not have to be mkdir.
            policy: Confinement override. Defaults to write access to
                the workspace and nothing else.
            network_allowed: Whether commands may reach the network.
                Ignored when ``policy`` is given explicitly.
        """
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve()
        _ensure_metadata_directory(self.root)
        self.policy = policy or workspace_write(
            self.root, network_allowed=network_allowed
        )

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
