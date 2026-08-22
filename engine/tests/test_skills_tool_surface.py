"""Which consumer gets the skills surface, and which deliberately does not."""

from __future__ import annotations

import pathlib

import pytest

from co_scientist.agents.reflection import simulation_execution
from co_scientist.sandbox import SandboxKind, SandboxPolicy
from co_scientist.skills import catalog
from co_scientist.workspace.tool_schemas import READ_SKILL, RUN_COMMAND
from co_scientist.workspace.tools import workspace_tool_schemas

# Backend-exempt, so `can_run_commands` is true without a sandbox backend
# on the host running the tests -- which CI does not have.
_RUNNABLE = SandboxPolicy(kind=SandboxKind.DANGER_FULL_ACCESS)
_NOT_RUNNABLE = SandboxPolicy(kind=SandboxKind.WORKSPACE_WRITE)


@pytest.fixture(autouse=True)
def _clear_cache() -> object:
    """Drops the process-wide catalogue around every test."""
    catalog.available_skills.cache_clear()
    yield
    catalog.available_skills.cache_clear()


def _install_skill(root: pathlib.Path, name: str) -> None:
    """Writes one usable skill into a directory."""
    (root / name / "scripts").mkdir(parents=True)
    (root / name / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Queries things.\n---\n\nBody.\n",
        encoding="utf-8",
    )


def _tool_names(policy: SandboxPolicy, *, enabled: bool = True) -> set[str]:
    """Returns the tool names offered under a policy."""
    return {
        schema["function"]["name"]
        for schema in workspace_tool_schemas(policy, skills_enabled=enabled)
    }


def test_no_catalogue_offers_no_skill_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A checkout, a test and a CI job see exactly the old tool set."""
    monkeypatch.delenv(catalog.SKILLS_DIR_ENV, raising=False)
    assert READ_SKILL not in _tool_names(_RUNNABLE)


def test_catalogue_adds_the_skill_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """With skills installed the tool appears, enumerating their names."""
    _install_skill(tmp_path, "uniprot-database")
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))

    schemas = workspace_tool_schemas(_RUNNABLE, skills_enabled=True)

    (skill_schema,) = [
        schema for schema in schemas if schema["function"]["name"] == READ_SKILL
    ]
    # Enumerated rather than described: a name the model invents is then
    # refused by schema validation instead of costing a turn.
    assert skill_schema["function"]["parameters"]["properties"]["name"][
        "enum"
    ] == ["uniprot-database"]


def test_installing_the_bundle_does_not_arm_a_consumer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """A consumer that did not ask gets nothing, however much is installed.

    This is the whole point of the flag. The skills were measured
    negative in the simulation review and positive in drafting, so the
    deployment that installs them for the second must not silently hand
    them back to the first.
    """
    _install_skill(tmp_path, "chembl-database")
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))

    assert READ_SKILL not in _tool_names(_RUNNABLE, enabled=False)


def test_skills_are_withheld_where_commands_are(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Instructions whose every step is a command need a command tool.

    Offering the skills to a model that cannot run one would spend turns
    reading instructions it has no way to act on.
    """
    _install_skill(tmp_path, "pdb-database")
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(
        "co_scientist.workspace.tools.sandbox_backend", lambda: None
    )

    names = _tool_names(_NOT_RUNNABLE)

    assert RUN_COMMAND not in names
    assert READ_SKILL not in names


def test_the_simulation_review_stays_offline_with_skills_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The node measured worse with skills opens a plain workspace.

    Eighteen runs said retrieval competes with building and running a
    model here (see the module docstring). Pinning it means asserting on
    the session the node opens with a full catalogue installed, since
    that is the state a deployment enabling skills for drafting puts the
    process in.
    """
    _install_skill(tmp_path, "gnomad-database")
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
    opened: list[tuple[str, str]] = []

    def _open(run_id: str, hypothesis_id: str) -> _StubSession:
        opened.append((run_id, hypothesis_id))
        return _StubSession(tmp_path / "ws")

    monkeypatch.setattr(simulation_execution, "open_review_workspace", _open)

    simulation_execution._tool_provider("run-1", "hyp-1")

    # No network_allowed and no skills_enabled among the arguments: the
    # node asks for a plain workspace and takes the defaults.
    assert opened == [("run-1", "hyp-1")]
    assert "no network access" in simulation_execution._NO_NETWORK_NOTE


class _StubSession:
    """The smallest thing ``_tool_provider`` needs back."""

    def __init__(self, root: pathlib.Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.policy = _RUNNABLE
        self.skills_enabled = False
