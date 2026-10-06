from __future__ import annotations

import pathlib
from typing import cast

import pytest

import co_scientist.agents.generation.literature_tools.draft as draft_skills
import co_scientist.skills as catalog
import co_scientist.skills as licences
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
    (directory / "SKILL.md").write_text(
        f"---\n{front}\n---\n\n{body}\n", encoding="utf-8"
    )
    return directory


def _install_skill(
    root: pathlib.Path, name: str, description: str = "Queries things."
) -> None:
    _write_skill(root, name, f"name: {name}\ndescription: {description}")


def _write_script(directory: pathlib.Path, deps: str) -> None:
    (directory / "scripts" / "cli.py").write_text(
        f"# /// script\n# dependencies = [\n{deps}# ]\n# ///\n",
        encoding="utf-8",
    )


def _venv(root: pathlib.Path, *installed: str) -> str:
    site = root / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    for name in installed:
        (site / f"{name}-1.0.dist-info").mkdir()
    (root / "bin").mkdir()
    return str(root / "bin" / "python")


@pytest.mark.usefixtures(
    "_clear_distribution_cache", "_skills_catalog_clear_cache"
)
class TestSkillsCatalog:
    @pytest.mark.parametrize(
        "front",
        [
            "description: no name here",
            "name: nameless-description",
            "name: [not, a, string]\ndescription:",
            ": : :",
        ],
    )
    def test_unusable_frontmatter_is_skipped_not_defaulted(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pathlib.Path,
        front: str,
    ) -> None:
        """Guessing descriptions would offer a skill with an invented
        purpose."""
        _write_skill(tmp_path, "broken", front)
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
        assert catalog.available_skills() == ()

    @pytest.mark.parametrize(
        ("skills", "interpreter", "expected"),
        [
            # Command-only instructions without a script leave the model at a
            # dead end.
            (
                [("pymol", None), ("string", '#   "polite-http",\n')],
                "venv",
                ["string"],
            ),
            # Unusable instructions spend turns before failing at invocation.
            (
                [
                    ("alphagenome", '#   "alphagenome",\n#   "jax",\n'),
                    ("string", '#   "polite-http",\n'),
                ],
                "venv",
                ["string"],
            ),
            # Unknown installation state differs from a known missing
            # dependency.
            (
                [("alphagenome", '#   "alphagenome",\n')],
                "python3",
                ["alphagenome"],
            ),
        ],
        ids=[
            "nothing-to-run",
            "dependency-missing",
            "unrecognised-interpreter",
        ],
    )
    def test_a_skill_that_cannot_be_used_is_withheld(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pathlib.Path,
        skills: list[tuple[str, str | None]],
        interpreter: str,
        expected: list[str],
    ) -> None:
        for name, dependencies in skills:
            _write_skill(
                tmp_path / "skills",
                name,
                f"name: {name}\ndescription: Queries things.",
                runnable=dependencies is not None,
            )
            if dependencies is not None:
                _write_script(tmp_path / "skills" / name, dependencies)
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path / "skills"))
        monkeypatch.setenv(
            catalog.SKILLS_PYTHON_ENV,
            _venv(tmp_path / "venv", "polite_http")
            if interpreter == "venv"
            else interpreter,
        )

        assert [s.name for s in catalog.available_skills()] == expected

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

        text = catalog.read_skill_document(
            "string", "references/interactions.md"
        )

        assert text is not None
        assert "partners --identifiers" in text
        assert "Skill directory:" not in text
        assert catalog.read_skill_document("string", "../secret.txt") is None
        assert catalog.read_skill_document("string", "/etc/hosts") is None


_PREREQUISITE = """---
name: {name}
description: Queries {name}.
---

## Prerequisites

1.  **User Notification**: If .licenses/{name}_LICENSE.txt does not already
    exist in the workspace root directory then (1) prominently notify the
    user to check the terms at https://example.org/terms, then (2) create
    the file recording the notification text and timestamp.
"""

_NO_PREREQUISITE = """---
name: {name}
description: Queries {name}.
---

Just run the script.
"""


@pytest.fixture
def _skills_licences_clear_cache() -> object:
    """The process-wide catalogue assumes a fixed directory; tests change it."""
    catalog.available_skills.cache_clear()
    yield
    catalog.available_skills.cache_clear()


def _skills_licences_install(
    root: pathlib.Path, name: str, template: str
) -> None:
    (root / name / "scripts").mkdir(parents=True)
    # A skill with no script is withheld from the catalogue, so a
    # fixture without one would test that rule instead of this file's.
    (root / name / "scripts" / "cli.py").write_text("", encoding="utf-8")
    (root / name / "SKILL.md").write_text(
        template.format(name=name), encoding="utf-8"
    )


@pytest.mark.usefixtures("_skills_licences_clear_cache")
class TestSkillsLicences:
    def test_no_skills_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        monkeypatch.delenv(catalog.SKILLS_DIR_ENV, raising=False)
        assert licences.seed_licence_notices(tmp_path) == 0
        assert not (tmp_path / licences.LICENCES_DIRNAME).exists()

    def test_a_skill_without_the_prerequisite_is_left_alone(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        skills_dir = tmp_path / "skills"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _skills_licences_install(skills_dir, "asks", _PREREQUISITE)
        _skills_licences_install(skills_dir, "quiet", _NO_PREREQUISITE)
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(skills_dir))

        assert licences.seed_licence_notices(workspace) == 1

    def test_an_unwritable_workspace_degrades_rather_than_raising(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Cosmetic notices must not prevent opening the review workspace."""
        skills_dir = tmp_path / "skills"
        _skills_licences_install(skills_dir, "europepmc", _PREREQUISITE)
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(skills_dir))
        # A file where the workspace belongs fails even for root.
        workspace = tmp_path / "ws"
        workspace.write_text("")
        assert licences.seed_licence_notices(workspace) == 0


# Backend-exempt, so `can_run_commands` is true without a sandbox backend
# on the host running the tests -- which CI does not have.


_STATE: WorkflowState = {"research_goal": "a goal", "run_id": "run-1"}  # type: ignore[typeddict-item]


class _StubProvider:
    """Stands in for the MCP provider the phase already resolved."""


_MCP_TOOLS = [{"type": "function", "function": {"name": "search_pubmed"}}]


@pytest.mark.usefixtures("_skills_catalog_clear_cache")
class TestSkillsDraftPhase:
    @pytest.mark.parametrize(
        ("installed", "run_id", "campaign"),
        [
            (False, "run-1", False),
            # No run id means no scoped workspace; hypotheses must still
            # survive.
            (True, None, False),
            # The campaign uses the guarded MCP without remote skill
            # instructions.
            (True, "run-1", True),
        ],
        ids=["no-skills", "no-run-id", "campaign"],
    )
    def test_the_phase_is_left_exactly_as_it_was_where_skills_cannot_attach(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pathlib.Path,
        installed: bool,
        run_id: str | None,
        campaign: bool,
    ) -> None:
        if installed:
            _install_skill(tmp_path / "skills", "uniprot", "Queries UniProt.")
            monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path / "skills"))
        else:
            monkeypatch.delenv(catalog.SKILLS_DIR_ENV, raising=False)
        if campaign:
            monkeypatch.setenv("COSCIENTIST_WORKSPACE_DIR", str(tmp_path / "w"))
            monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
        state = {**_STATE, "run_id": run_id}
        if run_id is None:
            del state["run_id"]
        provider = _StubProvider()

        attached = draft_skills.attach_skills(
            cast(WorkflowState, state), provider, _MCP_TOOLS
        )

        assert attached.provider is provider
        assert attached.tools == _MCP_TOOLS
        assert attached.section == ""
        assert attached.max_prompt_tokens == DEFAULT_TOOL_LOOP_TOKEN_BUDGET
        assert not (tmp_path / "w").exists()

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

        attached = draft_skills.attach_skills(
            _STATE, _StubProvider(), _MCP_TOOLS
        )

        names = {
            schema["function"]["name"]
            for schema in attached.tools
            if "function" in schema
        }
        assert READ_SKILL in names
        assert "search_pubmed" in names
        # The transcript backstop binds before the turn limit; more turns cannot
        # fund skills.
        assert attached.max_prompt_tokens > DEFAULT_TOOL_LOOP_TOKEN_BUDGET
        # The catalogue is resent on every transcript turn, so it carries
        # summaries rather than full descriptions.
        assert "uniprot: Queries UniProt." in attached.section
        assert "second sentence" not in attached.section
