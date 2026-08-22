"""Where the skills surface appears, and where it deliberately does not."""

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


def _tool_names(policy: SandboxPolicy) -> set[str]:
    """Returns the tool names offered under a policy."""
    return {
        schema["function"]["name"] for schema in workspace_tool_schemas(policy)
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

    schemas = workspace_tool_schemas(_RUNNABLE)

    (skill_schema,) = [
        schema for schema in schemas if schema["function"]["name"] == READ_SKILL
    ]
    # Enumerated rather than described: a name the model invents is then
    # refused by schema validation instead of costing a turn.
    assert skill_schema["function"]["parameters"]["properties"]["name"][
        "enum"
    ] == ["uniprot-database"]


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


def test_environment_note_tracks_the_catalogue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """What the prompt claims about the network follows what is installed.

    A model told it has no network will not look a constant up, and one
    told it has skills it does not have spends turns finding out.
    """
    monkeypatch.delenv(catalog.SKILLS_DIR_ENV, raising=False)
    assert "no network access" in simulation_execution._environment_note()

    catalog.available_skills.cache_clear()
    _install_skill(tmp_path, "gnomad-database")
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))

    note = simulation_execution._environment_note()

    assert "no network access" not in note
    assert "gnomad-database: Queries things." in note
    assert "read_skill" in note
