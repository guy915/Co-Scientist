from __future__ import annotations

import pathlib
from typing import cast

import pytest

import co_scientist.agents.generation.literature_tools.draft as draft_skills
import co_scientist.skills as catalog
import co_scientist.skills as credentials
import co_scientist.skills as licences
import co_scientist.skills as usage
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
    @pytest.mark.parametrize("directory", [None, "absent"])
    def test_an_unset_or_missing_directory_yields_no_skills(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pathlib.Path,
        directory: str | None,
    ) -> None:
        if directory is None:
            monkeypatch.delenv(catalog.SKILLS_DIR_ENV, raising=False)
        else:
            monkeypatch.setenv(
                catalog.SKILLS_DIR_ENV, str(tmp_path / directory)
            )
        assert catalog.available_skills() == ()
        assert catalog.catalogue_section() == ""

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

    def test_the_document_carries_the_invocation_and_the_output_rule(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Vendored examples name other directories and uv; the workspace
        constraint and the pinned interpreter must win."""
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
        assert "Every `--output /tmp/...` below is wrong here" in document
        assert document.index("Ignore any instruction") < document.index(
            "Run `uv run"
        )
        assert catalog.read_skill_document("chembl") is None
        assert catalog.find_skill("CHEMBL-Database") is not None

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
        # A file where the workspace belongs fails even for root.
        workspace = tmp_path / "ws"
        workspace.write_text("")
        assert licences.seed_licence_notices(workspace) == 0

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


@pytest.mark.usefixtures("_skills_catalog_clear_cache")
class TestSkillsToolSurface:
    @pytest.mark.parametrize(
        ("installed", "policy", "enabled", "offered"),
        [
            (True, _RUNNABLE, True, True),
            (False, _RUNNABLE, True, False),
            # Consumers enable skills independently; retrieval harmed measured
            # simulation quality.
            (True, _RUNNABLE, False, False),
            # Without a command tool, command-only instructions cannot be
            # followed.
            (True, _NOT_RUNNABLE, True, False),
        ],
        ids=["offered", "no-catalogue", "consumer-not-armed", "no-commands"],
    )
    def test_the_skill_tool_needs_a_catalogue_an_armed_consumer_and_commands(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pathlib.Path,
        installed: bool,
        policy: SandboxPolicy,
        enabled: bool,
        offered: bool,
    ) -> None:
        if installed:
            _install_skill(tmp_path, "uniprot-database")
            monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
        else:
            monkeypatch.delenv(catalog.SKILLS_DIR_ENV, raising=False)
        monkeypatch.setattr(
            "co_scientist.workspace.tools.sandbox_backend", lambda: None
        )

        schemas = workspace_tool_schemas(policy, skills_enabled=enabled)

        skill_schemas = [
            schema
            for schema in schemas
            if schema["function"]["name"] == READ_SKILL
        ]
        assert bool(skill_schemas) is offered
        if offered:
            # Enumerated rather than described: a name the model invents is
            # then refused by schema validation instead of costing a turn.
            (skill_schema,) = skill_schemas
            properties = skill_schema["function"]["parameters"]["properties"]
            assert properties["name"]["enum"] == ["uniprot-database"]
        if policy is _NOT_RUNNABLE:
            assert RUN_COMMAND not in _tool_names(policy)

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

    def test_draft_passes_open_with_the_network_and_the_skills_apart(
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

        assert first.skills_enabled
        assert first.policy.network_allowed
        assert first.root != second.root


@pytest.mark.usefixtures("_skills_catalog_clear_cache")
class TestSkillsAttribution:
    def test_an_invocation_is_attributed_to_its_own_source(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Licence and provenance attribution belongs to the invoked source,
        and executing model-written code is not use of a data source."""
        _write_skill(
            tmp_path,
            "string_database",
            "name: string-database\ndescription: Queries things.",
        )
        _install_skill(tmp_path, "chembl-database")
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
        monkeypatch.setenv(catalog.SKILLS_PYTHON_ENV, "/opt/venv/bin/python")
        argv = [
            "/opt/venv/bin/python",
            str(tmp_path / "string_database" / "scripts" / "cli.py"),
            "partners",
        ]

        with usage.scoped_skill_usage() as tally:
            assert credentials.invoked_skill(argv) == "string-database"
            assert (
                credentials.invoked_skill(
                    ["/opt/venv/bin/python", "analysis.py"]
                )
                is None
            )
            usage.record_skill_use("string-database")
            usage.record_skill_use("string-database")

        assert tally.snapshot() == {"string-database": 2}

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
