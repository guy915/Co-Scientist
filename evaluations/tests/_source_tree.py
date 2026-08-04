"""Shared discovery of the repo's first-party source files.

Both source-hygiene gates in this directory (`test_file_length.py` and
`test_function_length.py`) walk the same tree. The tree definition lives
here so a directory added to one gate cannot be missing from the other --
two drifting copies of "what counts as our code" is how a gate quietly
stops covering the file it was written for.
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

# First-party trees only. Everything else in the repo is either vendored,
# generated, or prose.
SOURCE_DIRS = (
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

# Directory names that never hold hand-written first-party source.
SKIP_DIRS = frozenset(
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

# Every test tree in this repo is a directory literally named `tests`
# (`app/tests`, `engine/tests`, `engine/mcp_server/tests`, `e2e/tests`,
# `evaluations/tests`), and no first-party source directory shares that
# name. Matching on the segment rather than listing the five paths means a
# test tree added later is classified correctly without an edit here.
TEST_DIR_NAME = "tests"


def is_skipped(path: pathlib.Path) -> bool:
    """Reports whether any path segment marks the file as not first-party.

    Returns:
        True when the file sits under a cache, vendored, or generated
        directory, or inside an egg-info metadata directory.
    """
    return any(
        part in SKIP_DIRS or part.endswith(".egg-info") for part in path.parts
    )


def is_test_file(path: pathlib.Path) -> bool:
    """Reports whether a path belongs to one of the repo's test trees.

    Returns:
        True when any segment of the path is a `tests` directory.
    """
    return TEST_DIR_NAME in path.parts


def source_files(suffixes: tuple[str, ...]) -> list[pathlib.Path]:
    """Collects every first-party source file with one of `suffixes`.

    Args:
        suffixes: File extensions to collect, each including the dot.

    Returns:
        Repo-relative paths, sorted and de-duplicated.
    """
    found: list[pathlib.Path] = []
    for source_dir in SOURCE_DIRS:
        base = ROOT / source_dir
        if not base.is_dir():
            continue
        for suffix in suffixes:
            found.extend(
                path.relative_to(ROOT)
                for path in base.rglob(f"*{suffix}")
                if not is_skipped(path)
            )
    return sorted(set(found))
