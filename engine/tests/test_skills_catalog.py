from __future__ import annotations

import pathlib

import pytest

import co_scientist.agents.generation.literature_tools.draft as draft_skills
import co_scientist.skills as catalog
from co_scientist.llm import DEFAULT_TOOL_LOOP_TOKEN_BUDGET
from co_scientist.state import WorkflowState
from co_scientist.workspace.tool_schemas import READ_SKILL


@pytest.fixture
def _clear_distribution_cache() -> object:
    """Installed-package discovery is cached across interpreter fixtures."""
    catalog._installed_distributions.cache_clear()
    yield
    catalog._installed_distributions.cache_clear()


@pytest.fixture
def _skills_catalog_clear_cache() -> object:
    """The process-wide catalogue assumes a fixed directory; tests change it."""
    catalog.available_skills.cache_clear()
    yield
    catalog.available_skills.cache_clear()


def _write_skill(
    root: pathlib.Path,
    folder: str,
    front: str,
    body: str = "Body.",
    *,
    runnable: bool = True,
) -> pathlib.Path:
    """A runnable script keeps fixtures from accidentally testing
    withholding."""
    directory = root / folder
    (directory / "scripts").mkdir(parents=True)
    if runnable:
        (directory / "scripts" / "cli.py").write_text("", encoding="utf-8")
    (directory / "SKILL.md").write_text(f"---\n{front}\n---\n\n{body}\n", encoding="utf-8")
    return directory


def _install_skill(root: pathlib.Path, name: str, description: str = "Queries things.") -> None:
    _write_skill(root, name, f"name: {name}\ndescription: {description}")


@pytest.mark.usefixtures("_clear_distribution_cache", "_skills_catalog_clear_cache")
class TestSkillsCatalog:
    def test_a_reference_file_is_reachable_but_never_outside_the_skill(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Bundles disclose an overview first and reference files second, and
        the path comes from the model and cannot be trusted."""
        directory = _write_skill(
            tmp_path,
            "string",
            "name: string\ndescription: Queries STRING.",
            body="See references/interactions.md.",
        )
        (directory / "references").mkdir()
        (directory / "references" / "interactions.md").write_text(
            "Run `string_cli.py partners --identifiers TP53`.\n",
            encoding="utf-8",
        )
        (tmp_path / "secret.txt").write_text("not yours", encoding="utf-8")
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))

        text = catalog.read_skill_document("string", "references/interactions.md")

        assert text is not None
        assert "partners --identifiers" in text
        assert "Skill directory:" not in text
        assert catalog.read_skill_document("string", "../secret.txt") is None
        assert catalog.read_skill_document("string", "/etc/hosts") is None


# Backend-exempt, so `can_run_commands` is true without a sandbox backend
# on the host running the tests -- which CI does not have.


_STATE: WorkflowState = {"research_goal": "a goal", "run_id": "run-1"}  # type: ignore[typeddict-item]


class _StubProvider:
    """Stands in for the MCP provider the phase already resolved."""


_MCP_TOOLS = [{"type": "function", "function": {"name": "search_pubmed"}}]


@pytest.mark.usefixtures("_skills_catalog_clear_cache")
class TestSkillsDraftPhase:
    def test_skills_attach_beside_the_search_tools(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        _install_skill(
            tmp_path / "skills",
            "uniprot",
            "Queries UniProt. Then a second sentence nobody needs to route.",
        )
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path / "skills"))
        monkeypatch.setattr(
            "co_scientist.workspace.run_workspace.workspaces_root",
            lambda: tmp_path / "ws",
        )

        attached = draft_skills.attach_skills(_STATE, _StubProvider(), _MCP_TOOLS)

        names = {schema["function"]["name"] for schema in attached.tools if "function" in schema}
        assert READ_SKILL in names
        assert "search_pubmed" in names
        # The transcript backstop binds before the turn limit; more turns cannot
        # fund skills.
        assert attached.max_prompt_tokens > DEFAULT_TOOL_LOOP_TOKEN_BUDGET
        # The catalogue is resent on every transcript turn, so it carries
        # summaries rather than full descriptions.
        assert "uniprot: Queries UniProt." in attached.section
        assert "second sentence" not in attached.section
