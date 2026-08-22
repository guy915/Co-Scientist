"""Seeding the licence notices 35 of the 38 skills demand up front."""

from __future__ import annotations

import pathlib

import pytest

from co_scientist.skills import catalog, licences

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


@pytest.fixture(autouse=True)
def _clear_cache() -> object:
    """Drops the process-wide catalogue around every test."""
    catalog.available_skills.cache_clear()
    yield
    catalog.available_skills.cache_clear()


def _install(root: pathlib.Path, name: str, template: str) -> None:
    """Writes one skill whose SKILL.md follows the given template."""
    (root / name).mkdir(parents=True)
    (root / name / "SKILL.md").write_text(
        template.format(name=name), encoding="utf-8"
    )


def test_no_skills_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """A deployment without skills gets no stray directory."""
    monkeypatch.delenv(catalog.SKILLS_DIR_ENV, raising=False)
    assert licences.seed_licence_notices(tmp_path) == 0
    assert not (tmp_path / licences.LICENCES_DIRNAME).exists()


def test_notice_lands_at_the_path_the_skill_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The filename is read from the skill, not derived from its folder.

    A re-pin that renames one would otherwise leave the model paying the
    four-turn toll again for a file seeded under the old name.
    """
    skills_dir = tmp_path / "skills"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _install(skills_dir, "europepmc", _PREREQUISITE)
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(skills_dir))

    assert licences.seed_licence_notices(workspace) == 1

    notice = (
        workspace / licences.LICENCES_DIRNAME / "europepmc_LICENSE.txt"
    ).read_text(encoding="utf-8")
    assert "europepmc" in notice
    assert "https://example.org/terms" in notice


def test_a_skill_without_the_prerequisite_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Only skills that ask for a notice get one."""
    skills_dir = tmp_path / "skills"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _install(skills_dir, "asks", _PREREQUISITE)
    _install(skills_dir, "quiet", _NO_PREREQUISITE)
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(skills_dir))

    assert licences.seed_licence_notices(workspace) == 1
    assert licences.notified_sources() == ("asks",)


def test_an_unwritable_workspace_degrades_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """A workspace that cannot hold notices still opens.

    Refusing here would turn a cosmetic problem into a lost review, and
    the simulation is about to fail for a better reason anyway.
    """
    skills_dir = tmp_path / "skills"
    _install(skills_dir, "europepmc", _PREREQUISITE)
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(skills_dir))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    workspace.chmod(0o500)
    try:
        assert licences.seed_licence_notices(workspace) == 0
    finally:
        workspace.chmod(0o700)


def test_every_vendored_skill_that_asks_is_covered() -> None:
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
        and ".licenses/" in (directory / "SKILL.md").read_text(encoding="utf-8")
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
