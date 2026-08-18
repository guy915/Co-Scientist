"""Tests for shadow-git workspace snapshots.

The property that matters is invisibility: the workspace's own git
history must be untouched, because a run may be snapshotting a
repository its user is also working in.
"""

import shutil
from pathlib import Path

import pytest

from co_scientist.sandbox.policy import SandboxKind, SandboxPolicy
from co_scientist.sandbox.runner import ExecRequest, run_sandboxed
from co_scientist.workspace.snapshot import WorkspaceSnapshotter

_requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed"
)
_TRUSTED = SandboxPolicy(kind=SandboxKind.DANGER_FULL_ACCESS)


async def _git(cwd: Path, *args: str) -> str:
    """Runs git in a directory and returns its stdout."""
    result = await run_sandboxed(
        ExecRequest(
            argv=["git", *args],
            policy=_TRUSTED,
            cwd=cwd,
            timeout_seconds=60,
        )
    )
    return result.stdout


def _snapshotter(tmp_path: Path) -> WorkspaceSnapshotter:
    """Builds a snapshotter over a fresh workspace."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return WorkspaceSnapshotter(workspace, tmp_path / "shadow")


@_requires_git
@pytest.mark.asyncio
async def test_a_snapshot_returns_a_tree_hash(tmp_path: Path) -> None:
    snapshotter = _snapshotter(tmp_path)
    (snapshotter.workspace / "a.txt").write_text("content\n")

    snapshot = await snapshotter.take()

    assert snapshot is not None
    assert len(snapshot.tree) == 40


@_requires_git
@pytest.mark.asyncio
async def test_identical_content_yields_the_same_hash(
    tmp_path: Path,
) -> None:
    """Content-addressed, so provenance is comparable across runs."""
    snapshotter = _snapshotter(tmp_path)
    (snapshotter.workspace / "a.txt").write_text("content\n")

    first = await snapshotter.take()
    second = await snapshotter.take()

    assert first is not None and second is not None
    assert first.tree == second.tree


@_requires_git
@pytest.mark.asyncio
async def test_changed_content_yields_a_different_hash(
    tmp_path: Path,
) -> None:
    snapshotter = _snapshotter(tmp_path)
    target = snapshotter.workspace / "a.txt"
    target.write_text("before\n")
    first = await snapshotter.take()

    target.write_text("after\n")
    second = await snapshotter.take()

    assert first is not None and second is not None
    assert first.tree != second.tree


@_requires_git
@pytest.mark.asyncio
async def test_the_workspace_git_history_is_untouched(
    tmp_path: Path,
) -> None:
    """The central property.

    A run may snapshot a repository its user is also working in, so
    nothing may appear in that repository's log, refs, or index.
    """
    snapshotter = _snapshotter(tmp_path)
    workspace = snapshotter.workspace
    await _git(workspace, "init", "--quiet")
    await _git(workspace, "config", "user.email", "t@example.com")
    await _git(workspace, "config", "user.name", "t")
    (workspace / "a.txt").write_text("tracked\n")
    await _git(workspace, "add", "a.txt")
    await _git(workspace, "commit", "--quiet", "-m", "initial")

    log_before = await _git(workspace, "log", "--oneline")
    status_before = await _git(workspace, "status", "--porcelain")

    (workspace / "scratch.txt").write_text("agent output\n")
    snapshot = await snapshotter.take()

    assert snapshot is not None
    assert await _git(workspace, "log", "--oneline") == log_before
    # The untracked file is still untracked: the shadow `add` staged it
    # in the shadow index, not the workspace's.
    assert await _git(workspace, "status", "--porcelain") != status_before
    assert "scratch.txt" in await _git(workspace, "status", "--porcelain")


@_requires_git
@pytest.mark.asyncio
async def test_diffing_two_snapshots(tmp_path: Path) -> None:
    snapshotter = _snapshotter(tmp_path)
    target = snapshotter.workspace / "a.txt"
    target.write_text("before\n")
    first = await snapshotter.take()
    target.write_text("after\n")
    second = await snapshotter.take()

    assert first is not None and second is not None
    diff = await snapshotter.diff(first, second)

    assert diff is not None
    assert "-before" in diff
    assert "+after" in diff
