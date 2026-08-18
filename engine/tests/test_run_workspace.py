"""Tests for resolving a run's workspace directory.

Two properties matter here and neither is about tidiness.

Reopening must be idempotent, because this host kills and restarts
workers by design: a restarted task that resolved a *fresh* directory
would redo work whose output was already on disk, and the symptom would
be a slow run rather than an error.

The run id is untrusted input being turned into a path -- and that path is
then handed to the sandbox as a writable root, so a traversal here would
have the confinement argue for the escape rather than against it.
"""

from pathlib import Path

import pytest

from co_scientist.workspace import (
    WORKSPACE_DIR_ENV,
    WorkspaceIdError,
    build_workspace_tools,
    open_run_workspace,
    workspace_path,
    workspaces_root,
)


@pytest.fixture(autouse=True)
def _isolated_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keeps every test off the real workspaces directory."""
    monkeypatch.setenv(WORKSPACE_DIR_ENV, str(tmp_path / "workspaces"))


def test_reopening_a_run_returns_the_same_directory() -> None:
    """A restarted worker must find the files the killed one wrote."""
    first = open_run_workspace("run-abc")
    (first.root / "partial.csv").write_text("1,2\n")

    second = open_run_workspace("run-abc")

    assert second.root == first.root
    assert (second.root / "partial.csv").read_text() == "1,2\n"


def test_two_runs_do_not_share_a_workspace() -> None:
    assert open_run_workspace("run-a").root != open_run_workspace("run-b").root


def test_a_traversing_run_id_stays_under_the_root() -> None:
    """The resolved path becomes a writable root; traversal is an escape."""
    resolved = workspace_path("../../etc/shadow")
    assert workspaces_root() in resolved.parents


def test_a_run_id_with_nothing_usable_is_refused() -> None:
    """Sanitizing to empty would hand every such run one shared directory."""
    with pytest.raises(WorkspaceIdError):
        workspace_path("../..")


def test_the_workspace_is_the_only_writable_root() -> None:
    session = open_run_workspace("run-policy")
    assert session.policy.writable_roots == (session.root,)


def test_network_is_off_unless_asked_for() -> None:
    """Needing the internet is a decision, not the resting state."""
    assert not open_run_workspace("run-net").policy.allows_network
    assert open_run_workspace(
        "run-net-on", network_allowed=True
    ).policy.allows_network


def test_the_tool_provider_is_bound_to_the_run() -> None:
    provider = build_workspace_tools("run-tools")
    assert provider.session.root == workspace_path("run-tools")
