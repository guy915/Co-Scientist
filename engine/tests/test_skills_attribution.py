"""Counting the data sources a run reached, so the report can name them.

The obligation and why a workspace file does not discharge it are in
``skills/licences.py``. These pin the chain that does: a skill command
records the source by name, and a run that ran none records nothing.
"""

from __future__ import annotations

import pathlib

import pytest

from co_scientist.models import (
    ExecutionMetrics,
    MetricDeltas,
    create_metrics_update,
    merge_metrics,
)
from co_scientist.skills import catalog, credentials, usage


@pytest.fixture(autouse=True)
def _clear_cache() -> object:
    """Drops the process-wide catalogue around every test."""
    catalog.available_skills.cache_clear()
    yield
    catalog.available_skills.cache_clear()


def _install(root: pathlib.Path, folder: str, name: str) -> None:
    """Writes one skill directory with a runnable script."""
    (root / folder / "scripts").mkdir(parents=True)
    (root / folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Queries things.\n---\n\nBody.\n",
        encoding="utf-8",
    )
    (root / folder / "scripts" / "cli.py").write_text("", encoding="utf-8")


def test_an_invocation_is_attributed_to_its_own_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The skill is named, not merely counted.

    ``run_command`` is one tool name over every data source, so a count
    by tool name cannot say which terms a run owes. The notice is per
    source, so the attribution has to be too.
    """
    _install(tmp_path, "string_database", "string-database")
    _install(tmp_path, "chembl_database", "chembl-database")
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
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Running the same interpreter over other code attributes nothing.

    The drafting workspace runs model-written programs through the same
    interpreter, and naming a database the run never queried is a worse
    disclosure than naming none.
    """
    _install(tmp_path, "string_database", "string-database")
    monkeypatch.setenv(catalog.SKILLS_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(catalog.SKILLS_PYTHON_ENV, "/opt/venv/bin/python")

    assert (
        credentials.invoked_skill(["/opt/venv/bin/python", "analysis.py"])
        is None
    )


def test_recording_outside_a_scope_is_not_an_error() -> None:
    """A caller that never opened a scope costs nothing and raises nothing.

    The ``dev/`` scripts drive node functions directly, and no run
    without the bundle installed ever reaches a skill at all.
    """
    usage.record_skill_use("string-database")


def test_the_tally_accumulates_across_a_run() -> None:
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
