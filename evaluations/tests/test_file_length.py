"""Repo-wide file-length ceiling.

Every first-party source file stays at or below `MAX_LINES`. The rule is
old, but it was convention-only until this guard existed, and convention
alone did not hold: a July 2026 pass brought the tree under 500 lines, a
later complexity pass added extracted helpers back into the same files,
and 23 files silently crossed the line again. The metrics that survived
that window were the ones a checker enforced (ruff's complexity ceiling,
the parity ledger), so this ceiling gets a checker too.

Splitting is by concern into sibling modules that re-export the moved
names, so import paths and monkeypatch seams survive the split; see the
`engine_tasks_*` and `runs_*` families for the established shape.
"""

from __future__ import annotations

import pathlib

MAX_LINES = 500

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

# First-party trees only. Everything else in the repo is either vendored,
# generated, or prose.
_SOURCE_DIRS = (
    "app/app",
    "app/dev",
    "app/frontend/src",
    "app/tests",
    "e2e",
    "engine/dev",
    "engine/examples",
    "engine/mcp_server",
    "engine/src",
    "engine/tests",
    "evaluations",
)

_SOURCE_SUFFIXES = (".py", ".ts", ".tsx")

# Directory names that never hold hand-written first-party source.
_SKIP_DIRS = frozenset(
    {
        ".mypy_cache",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "cache",
        "datasets",
        "node_modules",
        "results",
    }
)


def _is_skipped(path: pathlib.Path) -> bool:
    """Reports whether any path segment marks the file as not first-party.

    Returns:
        True when the file sits under a cache, vendored, or generated
        directory, or inside an egg-info metadata directory.
    """
    return any(
        part in _SKIP_DIRS or part.endswith(".egg-info") for part in path.parts
    )


def _source_files() -> list[pathlib.Path]:
    """Collects every first-party source file in the repo.

    Returns:
        Repo-relative paths of the Python and TypeScript sources that the
        line ceiling applies to.
    """
    found: list[pathlib.Path] = []
    for source_dir in _SOURCE_DIRS:
        base = _ROOT / source_dir
        if not base.is_dir():
            continue
        for suffix in _SOURCE_SUFFIXES:
            found.extend(
                path.relative_to(_ROOT)
                for path in base.rglob(f"*{suffix}")
                if not _is_skipped(path)
            )
    return sorted(set(found))


def _line_count(path: pathlib.Path) -> int:
    """Counts the lines in one source file.

    Returns:
        The file's line count, matching what `wc -l` reports.
    """
    with (_ROOT / path).open(encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def test_no_source_file_exceeds_the_line_ceiling() -> None:
    """No first-party source file may exceed MAX_LINES."""
    files = _source_files()
    # A collection bug that finds nothing would make this test vacuous,
    # so pin that the walk still reaches the tree.
    assert len(files) > 400, f"only found {len(files)} source files"

    oversized = [
        (path, count)
        for path in files
        if (count := _line_count(path)) > MAX_LINES
    ]
    assert not oversized, "files over the {} line ceiling:\n{}".format(
        MAX_LINES,
        "\n".join(f"  {count:>5} {path}" for path, count in oversized),
    )
