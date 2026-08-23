"""Attaching the science skills to the hypothesis-drafting pass."""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from co_scientist.agents.generation.literature_tools import draft_skills
from co_scientist.llm_tool_policy import DEFAULT_TOOL_LOOP_TOKEN_BUDGET
from co_scientist.skills import catalog
from co_scientist.state import WorkflowState
from co_scientist.workspace.run_workspace import open_draft_workspace
from co_scientist.workspace.tool_schemas import READ_SKILL


@pytest.fixture(autouse=True)
def _clear_cache() -> object:
    """Drops the process-wide catalogue around every test."""
    catalog.available_skills.cache_clear()
    yield
    catalog.available_skills.cache_clear()


def _install_skill(root: pathlib.Path, name: str, description: str) -> None:
    """Writes one usable skill into a directory."""
    (root / name / "scripts").mkdir(parents=True)
    # A skill with no script is withheld from the catalogue, so a
    # fixture without one would test that rule instead of this file's.
    (root / name / "scripts" / "cli.py").write_text("", encoding="utf-8")
    (root / name / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nBody.\n",
        encoding="utf-8",
    )


def _state(run_id: str | None = "run-1") -> WorkflowState:
    """The two state values attaching actually reads."""
    state: dict[str, Any] = {"research_goal": "a goal"}
    if run_id is not None:
        state["run_id"] = run_id
    return state  # type: ignore[return-value]


class _StubProvider:
    """Stands in for the MCP provider the phase already resolved."""


_MCP_TOOLS = [{"type": "function", "function": {"name": "search_pubmed"}}]


def test_no_skills_leaves_the_phase_exactly_as_it_was(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A checkout, a test and a CI job draft through the MCP tools alone."""
    monkeypatch.delenv(catalog.SKILLS_DIR_ENV, raising=False)
    provider = _StubProvider()

    attached = draft_skills.attach_skills(_state(), provider, _MCP_TOOLS)

    assert attached.provider is provider
    assert attached.tools == _MCP_TOOLS
    assert attached.section == ""
    assert attached.max_prompt_tokens == DEFAULT_TOOL_LOOP_TOKEN_BUDGET


def test_a_run_without_an_id_drafts_without_skills(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """A workspace is scoped to a run, so no run means no workspace.

    Degrading rather than raising, because a drafting pass without the
    skills is the whole job minus one instrument and a pass that raised
    would cost the cycle its hypotheses.
    """
    _install_skill(tmp_path, "uniprot", "Queries UniProt.")
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
    provider = _StubProvider()

    attached = draft_skills.attach_skills(
        _state(run_id=None), provider, _MCP_TOOLS
    )

    assert attached.provider is provider
    assert attached.section == ""


def test_skills_attach_beside_the_search_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The model sees one surface: the databases and the search tools.

    The skills return records and the search tools return papers, so
    losing either half in the merge would narrow the drafting rather
    than widen it.
    """
    _install_skill(tmp_path / "skills", "uniprot", "Queries UniProt.")
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path / "skills"))
    monkeypatch.setattr(
        "co_scientist.workspace.run_workspace.workspaces_root",
        lambda: tmp_path / "ws",
    )

    attached = draft_skills.attach_skills(_state(), _StubProvider(), _MCP_TOOLS)

    names = {
        schema["function"]["name"]
        for schema in attached.tools
        if "function" in schema
    }
    assert READ_SKILL in names
    assert "search_pubmed" in names
    # Turns are not what binds this loop -- live passes stop six or
    # seven turns into a thirteen-turn budget, on the transcript
    # backstop. Funding skills with more turns buys nothing.
    assert attached.max_prompt_tokens > DEFAULT_TOOL_LOOP_TOKEN_BUDGET


def test_the_prompt_section_carries_summaries_not_full_descriptions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Every line here is re-sent on every turn of the loop.

    Measured on a live loop, the bundle's full descriptions cost ~2.4k
    tokens a turn -- more than every tool result in it put together --
    which is why the catalogue is summarised to one sentence per skill.
    """
    _install_skill(
        tmp_path,
        "uniprot",
        "Queries UniProt. Then a second sentence nobody needs to route.",
    )
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))

    section = draft_skills.skills_section()

    assert "uniprot: Queries UniProt." in section
    assert "second sentence" not in section


def test_a_draft_workspace_opens_with_the_network_and_the_skills(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Both, or the skills are documents about APIs nobody can reach."""
    monkeypatch.setattr(
        "co_scientist.workspace.run_workspace.workspaces_root",
        lambda: tmp_path,
    )

    session = open_draft_workspace("run-1", "pass-1")

    assert session.skills_enabled
    assert session.policy.network_allowed


def test_two_passes_of_one_run_do_not_share_a_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """A cycle reading the previous cycle's result file as its own.

    Every generation cycle drafts, so reusing one directory per run
    leaves each pass looking at output it did not produce.
    """
    monkeypatch.setattr(
        "co_scientist.workspace.run_workspace.workspaces_root",
        lambda: tmp_path,
    )

    first = open_draft_workspace("run-1", "pass-1")
    second = open_draft_workspace("run-1", "pass-2")

    assert first.root != second.root
