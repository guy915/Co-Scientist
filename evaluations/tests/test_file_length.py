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

The tree walk lives in `_source_tree`, shared with the sibling
function-length gate.
"""

from __future__ import annotations

import pathlib

from evaluations.tests._source_tree import ROOT, source_files

MAX_LINES = 500

_SOURCE_SUFFIXES = (".py", ".ts", ".tsx")


def _line_count(path: pathlib.Path) -> int:
    """Counts the lines in one source file.

    Returns:
        The file's line count, matching what `wc -l` reports.
    """
    with (ROOT / path).open(encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def test_no_source_file_exceeds_the_line_ceiling() -> None:
    """No first-party source file may exceed MAX_LINES."""
    files = source_files(_SOURCE_SUFFIXES)
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
