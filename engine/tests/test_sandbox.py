"""Tests for confined command execution.

The argv-shape tests are cheap and check the contract. They are not the
point. The point is ``TestRealConfinement``, which runs actual commands
that try to escape and asserts they fail -- because every other kind of
test here passes just as happily against a sandbox that confines nothing,
which is the exact failure mode this module exists to avoid.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from co_scientist.sandbox import (
    PROTECTED_METADATA_NAMES,
    SandboxKind,
    SandboxPolicy,
    UnsupportedSandboxError,
    read_only,
    seatbelt,
    workspace_write,
    wrap_argv,
)
from co_scientist.sandbox import argv as sandbox_argv

_ON_MACOS = sys.platform == "darwin"

# Seatbelt-specific argv assertions only make sense on macOS.
_requires_seatbelt = pytest.mark.skipif(
    not _ON_MACOS, reason="seatbelt confinement is macOS-only"
)

# The escape tests, by contrast, are backend-agnostic: they go through
# wrap_argv and assert on what the kernel actually permitted. They must
# run on every platform that claims a backend -- Linux is production, and
# leaving it unexercised is how an unverified backend ships.
_requires_sandbox = pytest.mark.skipif(
    sandbox_argv.sandbox_backend() is None,
    reason="no sandbox backend on this platform",
)


def _bin(name: str) -> str:
    """Resolves a coreutil's absolute path for this platform.

    Hardcoding /bin or /usr/bin makes a test pass on one distribution
    and error on another, which reads as a confinement failure.
    """
    found = shutil.which(name)
    if found is None:  # pragma: no cover - environment-dependent
        pytest.skip(f"{name} is not installed")
    return found


# --- policy ---------------------------------------------------------------


def test_relative_writable_root_is_rejected() -> None:
    """A relative root would resolve against the sandboxed cwd, not ours."""
    with pytest.raises(ValueError, match="absolute"):
        SandboxPolicy(
            kind=SandboxKind.WORKSPACE_WRITE,
            writable_roots=(Path("relative/dir"),),
        )


def test_writable_roots_are_resolved(tmp_path: Path) -> None:
    """Roots are canonicalized at construction.

    Regression: the OS primitives match on the real path, so a root
    reached through a symlink grants nothing. On macOS every /var path is
    such a case, which made a granted directory silently unwritable. The
    original test missed it only because pytest's tmp_path arrives
    already resolved.
    """
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    assert workspace_write(link).writable_roots == (real.resolve(),)


def test_read_only_never_allows_network() -> None:
    assert not read_only().allows_network


def test_workspace_write_network_is_opt_in(tmp_path: Path) -> None:
    assert not workspace_write(tmp_path).allows_network
    assert workspace_write(tmp_path, network_allowed=True).allows_network


# --- wrapping -------------------------------------------------------------


def test_the_base_policy_ships_with_the_package() -> None:
    """The .sbpl is package data, and a missing one fails at run time.

    Without the pyproject package-data entry the file is absent from an
    installed wheel, so confinement breaks only in a real deployment --
    never in a source checkout, where every test here would still pass.
    """
    base = Path(seatbelt.__file__).with_name("seatbelt_base_policy.sbpl")
    assert base.is_file()
    assert "(deny default)" in base.read_text(encoding="utf-8")


def test_empty_command_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty command"):
        wrap_argv([], read_only())


def test_danger_full_access_passes_the_command_through() -> None:
    """Unconfined is honoured when the caller names it.

    The fail-closed test above protects against it happening by
    accident; asking for it explicitly is still allowed.
    """
    policy = SandboxPolicy(kind=SandboxKind.DANGER_FULL_ACCESS)
    assert wrap_argv(["echo", "hi"], policy) == ["echo", "hi"]


def test_external_confinement_passes_the_command_through() -> None:
    policy = SandboxPolicy(kind=SandboxKind.EXTERNAL)
    assert wrap_argv(["echo", "hi"], policy) == ["echo", "hi"]


def test_missing_backend_refuses_rather_than_running_unconfined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The load-bearing test in this file's cheap half.

    If this ever starts returning the bare argv, model-authored code runs
    unconfined on any platform we forgot to check, and nothing else in
    the suite would notice.
    """
    monkeypatch.setattr(sandbox_argv, "sandbox_backend", lambda: None)
    with pytest.raises(UnsupportedSandboxError, match="unconfined"):
        sandbox_argv.wrap_argv(["echo", "hi"], read_only())


@_requires_seatbelt
def test_writable_roots_are_passed_as_parameters_not_interpolated(
    tmp_path: Path,
) -> None:
    """Paths reach sandbox-exec as -D parameters.

    Interpolating them into the policy text would let a path containing a
    quote or newline rewrite the policy meant to contain it.
    """
    wrapped = wrap_argv(["echo", "hi"], workspace_write(tmp_path))
    policy_text = wrapped[wrapped.index("-p") + 1]
    assert str(tmp_path) not in policy_text
    assert f"-DWRITABLE_ROOT_0={tmp_path}" in wrapped


@_requires_seatbelt
def test_metadata_denial_is_emitted_after_the_write_allow(
    tmp_path: Path,
) -> None:
    """SBPL is last-match-wins, so order is the enforcement."""
    text = seatbelt.build_policy_text(workspace_write(tmp_path))
    assert text.index("(allow file-write*") < text.index("(deny file-write*")


# --- real confinement -----------------------------------------------------


def _run_confined(
    argv: list[str], policy: SandboxPolicy
) -> subprocess.CompletedProcess[str]:
    """Runs a command under the policy and returns the completed process."""
    return subprocess.run(
        wrap_argv(argv, policy),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@_requires_sandbox
class TestRealConfinement:
    """Commands that try to escape, and are expected to fail."""

    def test_a_confined_command_still_runs(self) -> None:
        """Baseline: if this fails, every denial below is meaningless."""
        result = _run_confined([_bin("echo"), "hello"], read_only())
        assert result.returncode == 0
        assert result.stdout.strip() == "hello"

    def test_write_succeeds_through_a_symlinked_root(
        self, tmp_path: Path
    ) -> None:
        """The end-to-end half of the resolution regression.

        Passing a symlinked root used to deny writes to the directory it
        granted -- a denial, so safe, but indistinguishable from a broken
        sandbox.
        """
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        target = real / "written.txt"

        result = _run_confined(
            [_bin("touch"), str(target)], workspace_write(link)
        )

        assert result.returncode == 0, result.stderr
        assert target.exists()

    def test_reads_are_permitted(self, tmp_path: Path) -> None:
        target = tmp_path / "readable.txt"
        target.write_text("content")
        result = _run_confined([_bin("cat"), str(target)], read_only())
        assert result.returncode == 0
        assert result.stdout == "content"

    def test_read_only_policy_denies_a_write(self, tmp_path: Path) -> None:
        target = tmp_path / "forbidden.txt"
        result = _run_confined([_bin("touch"), str(target)], read_only())
        assert result.returncode != 0
        assert not target.exists()

    def test_write_inside_a_writable_root_succeeds(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "allowed.txt"
        result = _run_confined(
            [_bin("touch"), str(target)], workspace_write(tmp_path)
        )
        assert result.returncode == 0, result.stderr
        assert target.exists()

    def test_write_outside_the_writable_root_is_denied(
        self, tmp_path: Path
    ) -> None:
        """The central claim: a granted root does not grant its siblings."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "outside.txt"
        result = _run_confined(
            [_bin("touch"), str(outside)], workspace_write(workspace)
        )
        assert result.returncode != 0
        assert not outside.exists()

    @pytest.mark.parametrize("name", PROTECTED_METADATA_NAMES)
    def test_metadata_inside_a_writable_root_is_protected(
        self, tmp_path: Path, name: str
    ) -> None:
        """A command may write to the workspace, not rewrite its records.

        Parametrized over the whole tuple rather than testing .git alone:
        both backends build these rules by iterating it, so a name added
        without a test looks protected in the source and is only ever
        confirmed by the one entry someone happened to check.
        """
        metadata_dir = tmp_path / name
        metadata_dir.mkdir()
        target = metadata_dir / "record"
        result = _run_confined(
            [_bin("touch"), str(target)], workspace_write(tmp_path)
        )
        assert result.returncode != 0
        assert not target.exists()

    def test_network_is_denied_by_default(self) -> None:
        """Outbound is denied unless the policy names it."""
        result = _run_confined(
            [
                _bin("curl"),
                "--max-time",
                "5",
                "-s",
                "https://example.com",
            ],
            workspace_write(),
        )
        assert result.returncode != 0
