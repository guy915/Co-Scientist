"""The skills catalogue: what it reads, what it refuses, what it renders."""

from __future__ import annotations

import pathlib

import pytest

from co_scientist.skills import catalog


@pytest.fixture(autouse=True)
def _clear_cache() -> object:
    """Drops the process-wide catalogue around every test.

    The catalogue is cached because it is read on every tool-loop turn
    and cannot change while the process runs. A test changing the
    directory is the one caller for which that is false.
    """
    catalog.available_skills.cache_clear()
    yield
    catalog.available_skills.cache_clear()


def _write_skill(
    root: pathlib.Path, folder: str, front: str, body: str = "Body."
) -> pathlib.Path:
    """Creates one skill directory with the given frontmatter."""
    directory = root / folder
    (directory / "scripts").mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\n{front}\n---\n\n{body}\n", encoding="utf-8"
    )
    return directory


def test_unset_directory_yields_no_skills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unconfigured deployment has an empty catalogue, not an error."""
    monkeypatch.delenv(catalog.SKILLS_DIR_ENV, raising=False)
    assert catalog.available_skills() == ()
    assert catalog.catalogue_section() == ""


def test_missing_directory_yields_no_skills(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """A path that is not a directory degrades rather than raising."""
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path / "absent"))
    assert catalog.available_skills() == ()


def test_catalogue_carries_name_and_description(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
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
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, front: str
) -> None:
    """A skill the model cannot be told the purpose of is not offered.

    Defaulting would advertise a skill with an empty or invented
    description, which the model would then invoke by guessing.
    """
    _write_skill(tmp_path, "broken", front)
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
    assert catalog.available_skills() == ()


def test_document_carries_the_invocation_the_file_does_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
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
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
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
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """An invented name returns None rather than a partial match."""
    _write_skill(
        tmp_path, "pdb", "name: pdb-database\ndescription: Structures."
    )
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
    assert catalog.read_skill_document("pdb") is None
    assert catalog.find_skill("PDB-Database") is not None


def test_a_reference_file_is_reachable_by_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The bundle's disclosure is two levels deep, so ours must be.

    20 of the 38 skills put the overview in SKILL.md and the command
    syntax in references/*.md. A model handed only the first level does
    not stop -- it guesses the arguments, which a live drafting pass did
    against STRING's CLI, for exit code 2.
    """
    (tmp_path / "string" / "references").mkdir(parents=True)
    (tmp_path / "string" / "SKILL.md").write_text(
        "---\nname: string\ndescription: Queries STRING.\n---\n\n"
        "See references/interactions.md.\n",
        encoding="utf-8",
    )
    (tmp_path / "string" / "references" / "interactions.md").write_text(
        "Run `string_cli.py partners --identifiers TP53`.\n", encoding="utf-8"
    )
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))

    text = catalog.read_skill_document("string", "references/interactions.md")

    assert text is not None
    assert "partners --identifiers" in text
    # The preamble belongs to the entry document, not to every page of it.
    assert "Skill directory:" not in text


def test_a_path_cannot_escape_the_skill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The model chooses this path, so it is checked rather than trusted."""
    (tmp_path / "string").mkdir(parents=True)
    (tmp_path / "string" / "SKILL.md").write_text(
        "---\nname: string\ndescription: Queries STRING.\n---\n\nBody.\n",
        encoding="utf-8",
    )
    (tmp_path / "secret.txt").write_text("not yours", encoding="utf-8")
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))

    assert catalog.read_skill_document("string", "../secret.txt") is None
    assert catalog.read_skill_document("string", "/etc/hosts") is None
