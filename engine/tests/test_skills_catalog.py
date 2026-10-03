from __future__ import annotations

import pathlib
from typing import Any

import pytest

import co_scientist.agents.generation.literature_tools.draft as draft_skills
import co_scientist.skills as catalog
import co_scientist.skills as credentials
import co_scientist.skills as licences
import co_scientist.skills as usage
from co_scientist.agents.reflection import simulation_execution
from co_scientist.llm import DEFAULT_TOOL_LOOP_TOKEN_BUDGET
from co_scientist.models import (
    ExecutionMetrics,
    MetricDeltas,
    create_metrics_update,
    merge_metrics,
)
from co_scientist.sandbox import SandboxKind, SandboxPolicy
from co_scientist.state import WorkflowState
from co_scientist.workspace.run_workspace import open_draft_workspace
from co_scientist.workspace.tool_schemas import READ_SKILL, RUN_COMMAND
from co_scientist.workspace.tools import workspace_tool_schemas


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
    def test_unset_directory_yields_no_skills(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv(catalog.SKILLS_DIR_ENV, raising=False)
        assert catalog.available_skills() == ()
        assert catalog.catalogue_section() == ""

    def test_missing_directory_yields_no_skills(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path / "absent"))
        assert catalog.available_skills() == ()

    def test_catalogue_carries_name_and_description(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        _write_skill(
            tmp_path,
            "uniprot",
            "name: uniprot-database\ndescription: >-\n  Protein\n  metadata.",
        )
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
        (skill,) = catalog.available_skills()
        assert skill.name == "uniprot-database"
        # Folded scalars arrive with newlines; the catalogue is one line per
        # skill, so a description spanning lines would break the rendering.
        assert skill.description == "Protein metadata."
        assert catalog.catalogue_section() == (
            "- uniprot-database: Protein metadata."
        )

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

    def test_a_skill_with_nothing_to_run_is_withheld(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Command-only instructions without a script leave the model at a
        dead end."""
        skills = tmp_path / "skills"
        _write_skill(
            skills,
            "pymol",
            "name: pymol\ndescription: Renders.",
            runnable=False,
        )
        _write_skill(
            skills, "string", "name: string-database\ndescription: Nets."
        )
        _write_script(skills / "string", '#   "polite-http",\n')
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(skills))
        monkeypatch.setenv(
            catalog.SKILLS_PYTHON_ENV, _venv(tmp_path / "venv", "polite_http")
        )

        assert [s.name for s in catalog.available_skills()] == [
            "string-database"
        ]

    def test_a_skill_its_interpreter_cannot_run_is_withheld(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Unusable instructions spend turns before failing at invocation."""
        skills = tmp_path / "skills"
        _write_skill(
            skills, "alphagenome", "name: alphagenome\ndescription: Variants."
        )
        _write_script(
            skills / "alphagenome", '#   "alphagenome",\n#   "jax",\n'
        )
        _write_skill(
            skills, "string", "name: string-database\ndescription: Networks."
        )
        _write_script(skills / "string", '#   "polite-http",\n')
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(skills))
        monkeypatch.setenv(
            catalog.SKILLS_PYTHON_ENV, _venv(tmp_path / "venv", "polite_http")
        )

        assert [s.name for s in catalog.available_skills()] == [
            "string-database"
        ]

    def test_an_unrecognised_interpreter_withholds_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Unknown installation state differs from a known missing
        dependency."""
        skills = tmp_path / "skills"
        _write_skill(
            skills, "alphagenome", "name: alphagenome\ndescription: Variants."
        )
        _write_script(skills / "alphagenome", '#   "alphagenome",\n')
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(skills))
        monkeypatch.setenv(catalog.SKILLS_PYTHON_ENV, "python3")

        assert [s.name for s in catalog.available_skills()] == ["alphagenome"]

    def test_document_carries_the_invocation_the_file_does_not(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        directory = _write_skill(
            tmp_path,
            "chembl",
            "name: chembl-database\ndescription: Molecules.",
            body="Run `uv run scripts/chembl_api.py`.",
        )
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
        monkeypatch.setenv(catalog.SKILLS_PYTHON_ENV, "/opt/venv/bin/python")

        document = catalog.read_skill_document("chembl-database")

        assert document is not None
        assert str(directory) in document
        assert "/opt/venv/bin/python" in document
        # The preamble overrides uv instructions without changing the pinned
        # vendor tree.
        assert "Run `uv run scripts/chembl_api.py`." in document
        assert document.index("Ignore any instruction") < document.index(
            "Run `uv run"
        )

    def test_the_document_says_where_output_may_be_written(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Vendored examples name other directories; the workspace constraint
        must win."""
        _write_skill(
            tmp_path,
            "string",
            "name: string-database\ndescription: Networks.",
            body="Write results with --output.",
        )
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))

        document = catalog.read_skill_document("string-database")

        assert document is not None
        assert "Every `--output /tmp/...` below is wrong here" in document

    def test_unknown_skill_reads_as_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        _write_skill(
            tmp_path, "pdb", "name: pdb-database\ndescription: Structures."
        )
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
        assert catalog.read_skill_document("pdb") is None
        assert catalog.find_skill("PDB-Database") is not None

    def test_a_reference_file_is_reachable_by_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Bundles disclose an overview first and reference files second."""
        (tmp_path / "string" / "references").mkdir(parents=True)
        (tmp_path / "string" / "scripts").mkdir(parents=True)
        (tmp_path / "string" / "scripts" / "cli.py").write_text(
            "", encoding="utf-8"
        )
        (tmp_path / "string" / "SKILL.md").write_text(
            "---\nname: string\ndescription: Queries STRING.\n---\n\n"
            "See references/interactions.md.\n",
            encoding="utf-8",
        )
        (tmp_path / "string" / "references" / "interactions.md").write_text(
            "Run `string_cli.py partners --identifiers TP53`.\n",
            encoding="utf-8",
        )
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))

        text = catalog.read_skill_document(
            "string", "references/interactions.md"
        )

        assert text is not None
        assert "partners --identifiers" in text
        assert "Skill directory:" not in text

    def test_a_path_cannot_escape_the_skill(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """The path comes from the model and cannot be trusted."""
        (tmp_path / "string" / "scripts").mkdir(parents=True)
        (tmp_path / "string" / "SKILL.md").write_text(
            "---\nname: string\ndescription: Queries STRING.\n---\n\nBody.\n",
            encoding="utf-8",
        )
        (tmp_path / "secret.txt").write_text("not yours", encoding="utf-8")
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))

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

    def test_notice_lands_at_the_path_the_skill_names(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Repinning a skill can change its required notice filename."""
        skills_dir = tmp_path / "skills"
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _skills_licences_install(skills_dir, "europepmc", _PREREQUISITE)
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(skills_dir))

        assert licences.seed_licence_notices(workspace) == 1

        notice = (
            workspace / licences.LICENCES_DIRNAME / "europepmc_LICENSE.txt"
        ).read_text(encoding="utf-8")
        assert "europepmc" in notice
        assert "https://example.org/terms" in notice

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
        workspace = tmp_path / "ws"
        workspace.mkdir()
        workspace.chmod(0o500)
        try:
            assert licences.seed_licence_notices(workspace) == 0
        finally:
            workspace.chmod(0o700)

    def test_every_vendored_skill_that_asks_is_covered(self) -> None:
        """Repinned prerequisite wording can break notice detection."""
        vendored = (
            pathlib.Path(__file__).resolve().parents[2]
            / "vendor"
            / "science-skills"
            / "skills"
        )
        if not vendored.is_dir():
            pytest.skip("vendored skills are not present in this checkout")
        asking = [
            directory
            for directory in vendored.iterdir()
            if (directory / "SKILL.md").is_file()
            and ".licenses/"
            in (directory / "SKILL.md").read_text(encoding="utf-8")
        ]
        recognised = [
            directory
            for directory in asking
            if licences._skill_notice(
                directory.name,
                (directory / "SKILL.md").read_text(encoding="utf-8"),
            )
            is not None
        ]
        assert len(asking) == 35
        assert recognised == asking


# Backend-exempt, so `can_run_commands` is true without a sandbox backend
# on the host running the tests -- which CI does not have.
_RUNNABLE = SandboxPolicy(kind=SandboxKind.DANGER_FULL_ACCESS)
_NOT_RUNNABLE = SandboxPolicy(kind=SandboxKind.WORKSPACE_WRITE)


@pytest.fixture
def _skills_tool_surface_clear_cache() -> object:
    """The process-wide catalogue assumes a fixed directory; tests change it."""
    catalog.available_skills.cache_clear()
    yield
    catalog.available_skills.cache_clear()


def _skills_tool_surface_install_skill(root: pathlib.Path, name: str) -> None:
    (root / name / "scripts").mkdir(parents=True)
    # A skill with no script is withheld from the catalogue, so a
    # fixture without one would test that rule instead of this file's.
    (root / name / "scripts" / "cli.py").write_text("", encoding="utf-8")
    (root / name / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Queries things.\n---\n\nBody.\n",
        encoding="utf-8",
    )


def _tool_names(policy: SandboxPolicy, *, enabled: bool = True) -> set[str]:
    return {
        schema["function"]["name"]
        for schema in workspace_tool_schemas(policy, skills_enabled=enabled)
    }


def _command_description(policy: SandboxPolicy) -> str:
    (schema,) = [
        schema
        for schema in workspace_tool_schemas(policy)
        if schema["function"]["name"] == RUN_COMMAND
    ]
    return str(schema["function"]["description"])


class _StubSession:
    def __init__(self, root: pathlib.Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.policy = _RUNNABLE
        self.skills_enabled = False


@pytest.mark.usefixtures("_skills_tool_surface_clear_cache")
class TestSkillsToolSurface:
    def test_no_catalogue_offers_no_skill_tool(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv(catalog.SKILLS_DIR_ENV, raising=False)
        assert READ_SKILL not in _tool_names(_RUNNABLE)

    def test_catalogue_adds_the_skill_tool(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        _skills_tool_surface_install_skill(tmp_path, "uniprot-database")
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))

        schemas = workspace_tool_schemas(_RUNNABLE, skills_enabled=True)

        (skill_schema,) = [
            schema
            for schema in schemas
            if schema["function"]["name"] == READ_SKILL
        ]
        # Enumerated rather than described: a name the model invents is then
        # refused by schema validation instead of costing a turn.
        assert skill_schema["function"]["parameters"]["properties"]["name"][
            "enum"
        ] == ["uniprot-database"]

    def test_installing_the_bundle_does_not_arm_a_consumer(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Consumers enable skills independently; retrieval harmed measured
        simulation quality."""
        _skills_tool_surface_install_skill(tmp_path, "chembl-database")
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))

        assert READ_SKILL not in _tool_names(_RUNNABLE, enabled=False)

    def test_skills_are_withheld_where_commands_are(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Without a command tool, command-only instructions cannot be
        followed."""
        _skills_tool_surface_install_skill(tmp_path, "pdb-database")
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
        monkeypatch.setattr(
            "co_scientist.workspace.tools.sandbox_backend", lambda: None
        )

        names = _tool_names(_NOT_RUNNABLE)

        assert RUN_COMMAND not in names
        assert READ_SKILL not in names

    def test_the_command_tool_describes_the_network_it_actually_has(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Runtime instructions must describe the actual network policy."""
        # A confined policy is the one whose sentence can differ, and it is
        # offered only where a backend exists -- which CI's host lacks.
        monkeypatch.setattr(
            "co_scientist.workspace.tools.sandbox_backend", lambda: object()
        )
        offline = SandboxPolicy(kind=SandboxKind.WORKSPACE_WRITE)
        online = SandboxPolicy(
            kind=SandboxKind.WORKSPACE_WRITE, network_allowed=True
        )

        assert "not reach the network" in _command_description(offline)
        assert "not reach the network" not in _command_description(online)

    def test_the_simulation_review_stays_offline_with_skills_installed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Retrieval competes with execution in the measured simulation
        workflow."""
        _skills_tool_surface_install_skill(tmp_path, "gnomad-database")
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
        opened: list[tuple[str, str]] = []

        def _open(run_id: str, hypothesis_id: str) -> _StubSession:
            opened.append((run_id, hypothesis_id))
            return _StubSession(tmp_path / "ws")

        monkeypatch.setattr(
            simulation_execution, "open_review_workspace", _open
        )

        simulation_execution._tool_provider("run-1", "hyp-1")

        assert opened == [("run-1", "hyp-1")]
        assert "no network access" in simulation_execution._NO_NETWORK_NOTE


@pytest.fixture
def _skills_draft_phase_clear_cache() -> object:
    """The process-wide catalogue assumes a fixed directory; tests change it."""
    catalog.available_skills.cache_clear()
    yield
    catalog.available_skills.cache_clear()


def _skills_draft_phase_install_skill(
    root: pathlib.Path, name: str, description: str
) -> None:
    (root / name / "scripts").mkdir(parents=True)
    # A skill with no script is withheld from the catalogue, so a
    # fixture without one would test that rule instead of this file's.
    (root / name / "scripts" / "cli.py").write_text("", encoding="utf-8")
    (root / name / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nBody.\n",
        encoding="utf-8",
    )


def _state(run_id: str | None = "run-1") -> WorkflowState:
    state: dict[str, Any] = {"research_goal": "a goal"}
    if run_id is not None:
        state["run_id"] = run_id
    return state  # type: ignore[return-value]


class _StubProvider:
    """Stands in for the MCP provider the phase already resolved."""


_MCP_TOOLS = [{"type": "function", "function": {"name": "search_pubmed"}}]


@pytest.mark.usefixtures("_skills_draft_phase_clear_cache")
class TestSkillsDraftPhase:
    def test_no_skills_leaves_the_phase_exactly_as_it_was(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv(catalog.SKILLS_DIR_ENV, raising=False)
        provider = _StubProvider()

        attached = draft_skills.attach_skills(_state(), provider, _MCP_TOOLS)

        assert attached.provider is provider
        assert attached.tools == _MCP_TOOLS
        assert attached.section == ""
        assert attached.max_prompt_tokens == DEFAULT_TOOL_LOOP_TOKEN_BUDGET

    def test_a_run_without_an_id_drafts_without_skills(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """No run id means no scoped workspace; hypotheses must still
        survive."""
        _skills_draft_phase_install_skill(
            tmp_path, "uniprot", "Queries UniProt."
        )
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
        provider = _StubProvider()

        attached = draft_skills.attach_skills(
            _state(run_id=None), provider, _MCP_TOOLS
        )

        assert attached.provider is provider
        assert attached.section == ""

    def test_skills_attach_beside_the_search_tools(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        _skills_draft_phase_install_skill(
            tmp_path / "skills", "uniprot", "Queries UniProt."
        )
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path / "skills"))
        monkeypatch.setattr(
            "co_scientist.workspace.run_workspace.workspaces_root",
            lambda: tmp_path / "ws",
        )

        attached = draft_skills.attach_skills(
            _state(), _StubProvider(), _MCP_TOOLS
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

    def test_the_prompt_section_carries_summaries_not_full_descriptions(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """The catalogue is resent on every transcript turn."""
        _skills_draft_phase_install_skill(
            tmp_path,
            "uniprot",
            "Queries UniProt. Then a second sentence nobody needs to route.",
        )
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))

        section = draft_skills.skills_section()

        assert "uniprot: Queries UniProt." in section
        assert "second sentence" not in section

    def test_a_draft_workspace_opens_with_the_network_and_the_skills(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        monkeypatch.setattr(
            "co_scientist.workspace.run_workspace.workspaces_root",
            lambda: tmp_path,
        )

        session = open_draft_workspace("run-1", "pass-1")

        assert session.skills_enabled
        assert session.policy.network_allowed

    def test_two_passes_of_one_run_do_not_share_a_directory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """A cycle must not mistake an earlier cycle's result file for its
        own."""
        monkeypatch.setattr(
            "co_scientist.workspace.run_workspace.workspaces_root",
            lambda: tmp_path,
        )

        first = open_draft_workspace("run-1", "pass-1")
        second = open_draft_workspace("run-1", "pass-2")

        assert first.root != second.root

    def test_campaign_uses_guarded_mcp_without_remote_skill_instructions(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        _skills_draft_phase_install_skill(
            tmp_path / "skills", "uniprot", "Queries UniProt."
        )
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path / "skills"))
        monkeypatch.setenv("COSCIENTIST_WORKSPACE_DIR", str(tmp_path / "work"))
        monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
        provider = _StubProvider()
        attached = draft_skills.attach_skills(_state(), provider, _MCP_TOOLS)
        assert attached.provider is provider
        assert attached.tools == _MCP_TOOLS
        assert attached.section == ""
        assert not (tmp_path / "work").exists()


@pytest.fixture
def _skills_attribution_clear_cache() -> object:
    """The process-wide catalogue assumes a fixed directory; tests change it."""
    catalog.available_skills.cache_clear()
    yield
    catalog.available_skills.cache_clear()


def _skills_attribution_install(
    root: pathlib.Path, folder: str, name: str
) -> None:
    (root / folder / "scripts").mkdir(parents=True)
    (root / folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Queries things.\n---\n\nBody.\n",
        encoding="utf-8",
    )
    (root / folder / "scripts" / "cli.py").write_text("", encoding="utf-8")


@pytest.mark.usefixtures("_skills_attribution_clear_cache")
class TestSkillsAttribution:
    def test_an_invocation_is_attributed_to_its_own_source(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Licence and provenance attribution belongs to the invoked source."""
        _skills_attribution_install(
            tmp_path, "string_database", "string-database"
        )
        _skills_attribution_install(
            tmp_path, "chembl_database", "chembl-database"
        )
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
        monkeypatch.setenv(catalog.SKILLS_PYTHON_ENV, "/opt/venv/bin/python")
        argv = [
            "/opt/venv/bin/python",
            str(tmp_path / "string_database" / "scripts" / "cli.py"),
            "partners",
        ]

        with usage.scoped_skill_usage() as tally:
            assert credentials.invoked_skill(argv) == "string-database"
            usage.record_skill_use("string-database")
            usage.record_skill_use("string-database")

        assert tally.snapshot() == {"string-database": 2}

    def test_a_program_of_the_models_own_is_not_a_data_source(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Executing model-written code is not use of a data source."""
        _skills_attribution_install(
            tmp_path, "string_database", "string-database"
        )
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
        monkeypatch.setenv(catalog.SKILLS_PYTHON_ENV, "/opt/venv/bin/python")

        assert (
            credentials.invoked_skill(["/opt/venv/bin/python", "analysis.py"])
            is None
        )

    def test_recording_outside_a_scope_is_not_an_error(self) -> None:
        usage.record_skill_use("string-database")

    def test_the_tally_accumulates_across_a_run(self) -> None:
        """Concurrent tasks and later cycles must add deltas, not overwrite
        totals."""
        merged = merge_metrics(
            ExecutionMetrics(skills_used={"string-database": 1}),
            create_metrics_update(
                deltas=MetricDeltas(
                    skills_used={"string-database": 2, "chembl-database": 1}
                )
            ),
        )

        assert merged.skills_used == {
            "string-database": 3,
            "chembl-database": 1,
        }
