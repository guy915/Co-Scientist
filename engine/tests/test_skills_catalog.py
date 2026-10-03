"""Offline contracts for skills catalog."""

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
    """Drops the interpreter's installed-package scan around every test."""
    catalog._installed_distributions.cache_clear()
    yield
    catalog._installed_distributions.cache_clear()


@pytest.fixture
def _skills_catalog_clear_cache() -> object:
    """Drops the process-wide catalogue around every test.

    The catalogue is cached because it is read on every tool-loop turn
    and cannot change while the process runs. A test changing the
    directory is the one caller for which that is false.
    """
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
    """Creates one skill directory with the given frontmatter.

    Runnable by default: a skill with no script is withheld from the
    catalogue, so a fixture without one would silently test that rule
    instead of whatever it meant to test.
    """
    directory = root / folder
    (directory / "scripts").mkdir(parents=True)
    if runnable:
        (directory / "scripts" / "cli.py").write_text("", encoding="utf-8")
    (directory / "SKILL.md").write_text(
        f"---\n{front}\n---\n\n{body}\n", encoding="utf-8"
    )
    return directory


def _write_script(directory: pathlib.Path, deps: str) -> None:
    """Writes one script declaring the given PEP 723 dependencies."""
    (directory / "scripts" / "cli.py").write_text(
        f"# /// script\n# dependencies = [\n{deps}# ]\n# ///\n",
        encoding="utf-8",
    )


def _venv(root: pathlib.Path, *installed: str) -> str:
    """Builds a venv-shaped tree and returns its interpreter path."""
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
        """An unconfigured deployment has an empty catalogue, not an error."""
        monkeypatch.delenv(catalog.SKILLS_DIR_ENV, raising=False)
        assert catalog.available_skills() == ()
        assert catalog.catalogue_section() == ""

    def test_missing_directory_yields_no_skills(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """A path that is not a directory degrades rather than raising."""
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path / "absent"))
        assert catalog.available_skills() == ()

    def test_catalogue_carries_name_and_description(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """A well-formed skill reaches the catalogue with both fields."""
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
        """A skill the model cannot be told the purpose of is not offered.

        Defaulting would advertise a skill with an empty or invented
        description, which the model would then invoke by guessing.
        """
        _write_skill(tmp_path, "broken", front)
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
        assert catalog.available_skills() == ()

    def test_a_skill_with_nothing_to_run_is_withheld(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Prose with no script is a dead end, so it is not offered.

        Every step of a skill's instructions is a command. Four of the 38
        vendored skills ship no script, and none is a data source: PyMOL
        needs a binary the image has no reason to carry, ``uv`` and
        ``credentials`` describe setup the harness has already done, and
        ``workflow_skill_creator`` authors new skills rather than using one.
        """
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
        """An uninstallable skill is not offered at all.

        Same reason ``run_command`` is withheld without a sandbox backend.
        Reading one costs a turn and then several thousand tokens re-sent on
        every turn after it, and the ImportError it returns is not something
        the model can act on. Two of the 38 vendored skills are this case in
        the api image, whose interpreter deliberately omits a 695 MB
        dependency closure.
        """
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
        """Not knowing what is installed offers everything, as before.

        "Unknown" must stay distinct from "nothing is installed": a layout
        this cannot read would otherwise empty the catalogue silently, which
        looks identical to the bundle not being installed at all.
        """
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
        """Reading a skill states the interpreter, since SKILL.md says uv."""
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
        # The vendored text is returned whole, uv instruction included: the
        # preamble overrides it rather than the file being edited, so the
        # tree stays byte-identical to the revision it is pinned to.
        assert "Run `uv run scripts/chembl_api.py`." in document
        assert document.index("Ignore any instruction") < document.index(
            "Run `uv run"
        )

    def test_the_document_says_where_output_may_be_written(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """The preamble names the one writable directory.

        Every script in the bundle defaults to file output rather than
        stdout -- that is one of its own authoring rules -- so the first
        correct invocation still dies unless the model knows the workspace
        is the only place it may write. A live drafting pass built a
        well-formed STRING query with ``--output /tmp/string_mapped.tsv``
        and lost it to ``PermissionError: Operation not permitted``, having
        already spent the API call. The instruction has to contradict the
        examples specifically rather than state the rule generally: 27 of
        the 38 vendored documents write ``--output /tmp/out.json`` in every
        example, and a model handed a general rule beside a dozen concrete
        counter-examples copies the examples -- which one did, twice, before
        correcting itself on the third attempt.
        """
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
        """An invented name returns None rather than a partial match."""
        _write_skill(
            tmp_path, "pdb", "name: pdb-database\ndescription: Structures."
        )
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
        assert catalog.read_skill_document("pdb") is None
        assert catalog.find_skill("PDB-Database") is not None

    def test_a_reference_file_is_reachable_by_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """The bundle's disclosure is two levels deep, so ours must be.

        20 of the 38 skills put the overview in SKILL.md and the command
        syntax in references/*.md. A model handed only the first level does
        not stop -- it guesses the arguments, which a live drafting pass did
        against STRING's CLI, for exit code 2.
        """
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
        # The preamble belongs to the entry document, not to every page of it.
        assert "Skill directory:" not in text

    def test_a_path_cannot_escape_the_skill(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """The model chooses this path, so it is checked rather than trusted."""
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
    """Drops the process-wide catalogue around every test."""
    catalog.available_skills.cache_clear()
    yield
    catalog.available_skills.cache_clear()


def _skills_licences_install(
    root: pathlib.Path, name: str, template: str
) -> None:
    """Writes one skill whose SKILL.md follows the given template."""
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
        """A deployment without skills gets no stray directory."""
        monkeypatch.delenv(catalog.SKILLS_DIR_ENV, raising=False)
        assert licences.seed_licence_notices(tmp_path) == 0
        assert not (tmp_path / licences.LICENCES_DIRNAME).exists()

    def test_notice_lands_at_the_path_the_skill_names(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """The filename is read from the skill, not derived from its folder.

        A re-pin that renames one would otherwise leave the model paying the
        four-turn toll again for a file seeded under the old name.
        """
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
        """Only skills that ask for a notice get one."""
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
        """A workspace that cannot hold notices still opens.

        Refusing here would turn a cosmetic problem into a lost review, and
        the simulation is about to fail for a better reason anyway.
        """
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
        """The real bundle's prerequisites are all recognised.

        Pins the parser against the tree actually shipped: a re-pin that
        changes the wording would otherwise reintroduce the toll silently,
        one skill at a time.
        """
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
    """Drops the process-wide catalogue around every test."""
    catalog.available_skills.cache_clear()
    yield
    catalog.available_skills.cache_clear()


def _skills_tool_surface_install_skill(root: pathlib.Path, name: str) -> None:
    """Writes one usable skill into a directory."""
    (root / name / "scripts").mkdir(parents=True)
    # A skill with no script is withheld from the catalogue, so a
    # fixture without one would test that rule instead of this file's.
    (root / name / "scripts" / "cli.py").write_text("", encoding="utf-8")
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


def _command_description(policy: SandboxPolicy) -> str:
    """Returns the run_command description offered under a policy."""
    (schema,) = [
        schema
        for schema in workspace_tool_schemas(policy)
        if schema["function"]["name"] == RUN_COMMAND
    ]
    return str(schema["function"]["description"])


class _StubSession:
    """The smallest thing ``_tool_provider`` needs back."""

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
        """A checkout, a test and a CI job see exactly the old tool set."""
        monkeypatch.delenv(catalog.SKILLS_DIR_ENV, raising=False)
        assert READ_SKILL not in _tool_names(_RUNNABLE)

    def test_catalogue_adds_the_skill_tool(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """With skills installed the tool appears, enumerating their names."""
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
        """A consumer that did not ask gets nothing, however much is installed.

        This is the whole point of the flag. The skills were measured
        negative in the simulation review and positive in drafting, so the
        deployment that installs them for the second must not silently hand
        them back to the first.
        """
        _skills_tool_surface_install_skill(tmp_path, "chembl-database")
        monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))

        assert READ_SKILL not in _tool_names(_RUNNABLE, enabled=False)

    def test_skills_are_withheld_where_commands_are(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Instructions whose every step is a command need a command tool.

        Offering the skills to a model that cannot run one would spend turns
        reading instructions it has no way to act on.
        """
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
        """The description tracks the policy rather than a fixed sentence.

        Telling a model the workspace "cannot reach the network" while the
        session permits egress contradicts the instruction it is acting on:
        every science skill is a remote query, and an attempt described as
        impossible is one no model has a reason to make.
        """
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
        """The node measured worse with skills opens a plain workspace.

        Eighteen runs said retrieval competes with building and running a
        model here (see the module docstring). Pinning it means asserting on
        the session the node opens with a full catalogue installed, since
        that is the state a deployment enabling skills for drafting puts the
        process in.
        """
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

        # No network_allowed and no skills_enabled among the arguments: the
        # node asks for a plain workspace and takes the defaults.
        assert opened == [("run-1", "hyp-1")]
        assert "no network access" in simulation_execution._NO_NETWORK_NOTE


@pytest.fixture
def _skills_draft_phase_clear_cache() -> object:
    """Drops the process-wide catalogue around every test."""
    catalog.available_skills.cache_clear()
    yield
    catalog.available_skills.cache_clear()


def _skills_draft_phase_install_skill(
    root: pathlib.Path, name: str, description: str
) -> None:
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


@pytest.mark.usefixtures("_skills_draft_phase_clear_cache")
class TestSkillsDraftPhase:
    def test_no_skills_leaves_the_phase_exactly_as_it_was(
        self,
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
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """A workspace is scoped to a run, so no run means no workspace.

        Degrading rather than raising, because a drafting pass without the
        skills is the whole job minus one instrument and a pass that raised
        would cost the cycle its hypotheses.
        """
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
        """The model sees one surface: the databases and the search tools.

        The skills return records and the search tools return papers, so
        losing either half in the merge would narrow the drafting rather
        than widen it.
        """
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
        # Turns are not what binds this loop -- live passes stop six or
        # seven turns into a thirteen-turn budget, on the transcript
        # backstop. Funding skills with more turns buys nothing.
        assert attached.max_prompt_tokens > DEFAULT_TOOL_LOOP_TOKEN_BUDGET

    def test_the_prompt_section_carries_summaries_not_full_descriptions(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Every line here is re-sent on every turn of the loop.

        Measured on a live loop, the bundle's full descriptions cost ~2.4k
        tokens a turn -- more than every tool result in it put together --
        which is why the catalogue is summarised to one sentence per skill.
        """
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
        """Both, or the skills are documents about APIs nobody can reach."""
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
    """Drops the process-wide catalogue around every test."""
    catalog.available_skills.cache_clear()
    yield
    catalog.available_skills.cache_clear()


def _skills_attribution_install(
    root: pathlib.Path, folder: str, name: str
) -> None:
    """Writes one skill directory with a runnable script."""
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
        """The skill is named, not merely counted.

        ``run_command`` is one tool name over every data source, so a count
        by tool name cannot say which terms a run owes. The notice is per
        source, so the attribution has to be too.
        """
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
        """Running the same interpreter over other code attributes nothing.

        The drafting workspace runs model-written programs through the same
        interpreter, and naming a database the run never queried is a worse
        disclosure than naming none.
        """
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
        """A caller that never opened a scope costs nothing and raises nothing.

        The ``dev/`` scripts drive node functions directly, and no run
        without the bundle installed ever reaches a skill at all.
        """
        usage.record_skill_use("string-database")

    def test_the_tally_accumulates_across_a_run(self) -> None:
        """Each node's delta sums into the run total the report reads.

        A run drafts in several cycles and, on the durable path, in several
        concurrent strategy tasks; last-write-wins would report only the
        final one's sources.
        """
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
