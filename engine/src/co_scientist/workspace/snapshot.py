"""Content snapshots of a workspace, taken without touching its history.

A snapshot is a git tree hash produced from a *separate* git directory
whose object store is linked into the workspace's own via
``objects/info/alternates``. Nothing is committed, no ref moves, and
``git log`` in the workspace is unchanged -- so a run can snapshot a
repository the user also works in without leaving traces in it.

Borrowed from opencode, and the reason it is worth borrowing here is
different from why they use it. For a coding agent this is undo. For a
hypothesis-testing system it is **provenance**: the tree hash answers
"which exact working state produced this result", so a verdict can be
tied to the code that generated it and a later reader can reconstruct
that state rather than trusting a description of it.

Snapshots degrade rather than fail. A workspace that is not a git
repository, or a host without git, yields None -- losing provenance is
not a reason to fail an experiment.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from co_scientist.sandbox.policy import SandboxKind, SandboxPolicy
from co_scientist.sandbox.runner import ExecRequest, run_sandboxed

logger = logging.getLogger(__name__)

# Snapshotting runs git against the host filesystem deliberately: it is
# our own command over our own paths, not model-authored code, and it
# must be able to read the workspace and write the shadow store.
_TRUSTED = SandboxPolicy(kind=SandboxKind.DANGER_FULL_ACCESS)

_SNAPSHOT_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class Snapshot:
    """A workspace's content at one moment.

    Attributes:
        tree: The git tree hash. Stable for identical content, so two
            runs reaching the same state share a value.
        shadow_dir: The git directory the snapshot was recorded in.
    """

    tree: str
    shadow_dir: Path


class WorkspaceSnapshotter:
    """Takes content snapshots of a workspace via a shadow git dir."""

    def __init__(self, workspace: Path, shadow_dir: Path) -> None:
        """Binds a snapshotter to a workspace and its shadow store.

        Args:
            workspace: The directory whose content is snapshotted.
            shadow_dir: Where the shadow git directory lives. Belongs
                off any small persistent volume -- these objects grow
                with the run and are not the durable record.
        """
        self.workspace = workspace.resolve()
        self.shadow_dir = shadow_dir.resolve()

    async def _git(self, *args: str) -> tuple[bool, str]:
        """Runs one git command against the shadow store."""
        result = await run_sandboxed(
            ExecRequest(
                argv=[
                    "git",
                    f"--git-dir={self.shadow_dir}",
                    f"--work-tree={self.workspace}",
                    *args,
                ],
                policy=_TRUSTED,
                cwd=self.workspace,
                timeout_seconds=_SNAPSHOT_TIMEOUT_SECONDS,
            )
        )
        return result.ok, (result.stdout if result.ok else result.stderr)

    async def _ensure_initialized(self) -> bool:
        """Creates the shadow store, sharing the workspace's objects."""
        if (self.shadow_dir / "HEAD").exists():
            return True
        self.shadow_dir.mkdir(parents=True, exist_ok=True)
        ok, message = await self._git("init", "--quiet")
        if not ok:
            logger.debug("shadow git init failed: %s", message)
            return False

        # Link the workspace's own object store so a snapshot only has
        # to write objects that differ from what is already there.
        real_objects = self.workspace / ".git" / "objects"
        if real_objects.is_dir():
            info = self.shadow_dir / "objects" / "info"
            info.mkdir(parents=True, exist_ok=True)
            (info / "alternates").write_text(
                f"{real_objects}\n", encoding="utf-8"
            )
        return True

    async def take(self) -> Snapshot | None:
        """Records the workspace's current content.

        Returns:
            The snapshot, or None when one could not be taken -- git is
            absent, or the workspace cannot be indexed. Losing
            provenance never fails the work that produced it.
        """
        if not await self._ensure_initialized():
            return None

        ok, message = await self._git("add", "--all")
        if not ok:
            logger.debug("shadow git add failed: %s", message)
            return None

        ok, output = await self._git("write-tree")
        if not ok:
            logger.debug("shadow git write-tree failed: %s", output)
            return None
        return Snapshot(tree=output.strip(), shadow_dir=self.shadow_dir)

    async def diff(self, earlier: Snapshot, later: Snapshot) -> str | None:
        """Returns the textual diff between two snapshots."""
        ok, output = await self._git(
            "diff", "--no-color", earlier.tree, later.tree
        )
        return output if ok else None
