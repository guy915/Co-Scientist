"""Tests for the workspace session.

The session is a convenience over the sandbox, not a boundary, so these
tests check that it composes the pieces correctly -- and, at the two
points where it resolves a path itself, that it refuses an escape.
"""

import shutil
from pathlib import Path

import pytest

from co_scientist.patch import PatchError
from co_scientist.sandbox import sandbox_backend
from co_scientist.workspace import (
    SPILL_DIRECTORY,
    OutputRecorder,
    WorkspaceSession,
)

_requires_sandbox = pytest.mark.skipif(
    sandbox_backend() is None, reason="no sandbox backend on this platform"
)


def _session(tmp_path: Path) -> WorkspaceSession:
    """Builds a session rooted at a fresh workspace."""
    return WorkspaceSession(tmp_path / "ws")


def test_the_root_is_created_if_absent(tmp_path: Path) -> None:
    session = WorkspaceSession(tmp_path / "made" / "here")
    assert session.root.is_dir()


@pytest.mark.asyncio
async def test_a_command_runs_inside_the_workspace(tmp_path: Path) -> None:
    session = _session(tmp_path)
    outcome = await session.run_command(["/bin/pwd"], timeout_seconds=30)
    assert outcome.result.ok, outcome.result.stderr
    assert outcome.result.stdout.strip() == str(session.root)


@pytest.mark.asyncio
async def test_a_read_only_command_needs_no_approval(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    outcome = await session.run_command(["/bin/echo", "x"], timeout_seconds=30)
    assert not outcome.required_approval


@pytest.mark.asyncio
async def test_an_unrecognized_command_is_flagged_for_approval(
    tmp_path: Path,
) -> None:
    """Flagged, not blocked -- the sandbox is what blocks.

    A command outside the read-only allowlist still runs; the flag is an
    audit record of what a human would have been asked about.
    """
    session = _session(tmp_path)
    flagged = await session.run_command(
        ["/usr/bin/tee", "out.txt"], timeout_seconds=30
    )
    assert flagged.required_approval


@pytest.mark.asyncio
async def test_a_command_cannot_write_outside_the_workspace(
    tmp_path: Path,
) -> None:
    """The composition that matters: session root becomes sandbox root."""
    session = _session(tmp_path)
    escape = tmp_path / "escaped.txt"
    outcome = await session.run_command(
        ["/usr/bin/touch", str(escape)], timeout_seconds=30
    )
    assert not outcome.result.ok
    assert not escape.exists()


@pytest.mark.asyncio
async def test_a_command_can_write_inside_the_workspace(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    outcome = await session.run_command(
        ["/usr/bin/touch", "made.txt"], timeout_seconds=30
    )
    assert outcome.result.ok, outcome.result.stderr
    assert (session.root / "made.txt").exists()


@pytest.mark.asyncio
async def test_the_host_environment_is_not_inherited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret")
    session = _session(tmp_path)
    outcome = await session.run_command(["/usr/bin/env"], timeout_seconds=30)
    assert "sk-secret" not in outcome.result.stdout


def test_patching_edits_files_in_the_workspace(tmp_path: Path) -> None:
    session = _session(tmp_path)
    (session.root / "a.py").write_text("old\n")

    outcome = session.apply_patch_text(
        "\n".join(
            [
                "*** Begin Patch",
                "*** Update File: a.py",
                "@@",
                "-old",
                "+new",
                "*** End Patch",
            ]
        )
    )

    assert outcome.changed == ("a.py",)
    assert (session.root / "a.py").read_text() == "new\n"


def test_reading_and_listing(tmp_path: Path) -> None:
    session = _session(tmp_path)
    (session.root / "sub").mkdir()
    (session.root / "sub" / "f.txt").write_text("content")

    assert session.read_file("sub/f.txt") == "content"
    assert session.list_files() == ("sub/f.txt",)


@pytest.mark.parametrize("path", ["../outside.txt", "sub/../../outside.txt"])
def test_reading_outside_the_workspace_is_refused(
    tmp_path: Path, path: str
) -> None:
    session = _session(tmp_path)
    (tmp_path / "outside.txt").write_text("secret")
    with pytest.raises(PatchError, match="outside the workspace"):
        session.read_file(path)


def test_a_failed_patch_reports_and_changes_nothing(tmp_path: Path) -> None:
    session = _session(tmp_path)
    (session.root / "a.py").write_text("actual\n")
    with pytest.raises(PatchError, match="did not match"):
        session.apply_patch_text(
            "\n".join(
                [
                    "*** Begin Patch",
                    "*** Update File: a.py",
                    "@@",
                    "-expected",
                    "+new",
                    "*** End Patch",
                ]
            )
        )
    assert (session.root / "a.py").read_text() == "actual\n"


@_requires_sandbox
@pytest.mark.asyncio
async def test_a_carve_out_backend_refuses_to_replace_the_metadata_dir(
    tmp_path: Path,
) -> None:
    """Only two of the three backends can express this.

    seatbelt denies by path and bwrap re-binds read-only; landlock rules
    can only *add* access, so it has no spelling for "writable, except
    here". Skipped rather than relaxed, because the guarantee genuinely
    differs by platform and a test that accepted either outcome would
    stop noticing if the two that can enforce it stopped.
    """
    if sandbox_backend() == "landlock":
        pytest.skip("landlock cannot express a carve-out; see the next test")
    link = shutil.which("ln")
    if link is None:  # pragma: no cover - environment-dependent
        pytest.skip("ln is not installed")
    session = _session(tmp_path)
    metadata = SPILL_DIRECTORY.split("/")[0]

    outcome = await session.run_command(
        [link, "-sfn", "/tmp", metadata], timeout_seconds=30
    )

    assert not outcome.result.ok
    assert not (session.root / metadata).is_symlink()


@_requires_sandbox
@pytest.mark.asyncio
async def test_replacing_the_metadata_dir_cannot_redirect_a_host_write(
    tmp_path: Path,
) -> None:
    """The invariant that does hold on every backend.

    Where the carve-out exists a command cannot replace the directory;
    where it does not, the command succeeds and the host's own write
    then refuses the redirected target. Either way nothing lands outside
    the workspace -- and this, not the carve-out, is what makes spilling
    output safe.
    """
    link = shutil.which("ln")
    if link is None:  # pragma: no cover - environment-dependent
        pytest.skip("ln is not installed")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    session = _session(tmp_path)
    metadata = SPILL_DIRECTORY.split("/")[0]

    await session.run_command(
        [link, "-sfn", str(outside), metadata], timeout_seconds=30
    )
    OutputRecorder(session.root, preview_chars=50).record("stdout", "x" * 900)

    assert list(outside.rglob("*")) == []
