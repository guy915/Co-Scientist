"""Parity-ledger checker.

Parses ``docs/PARITY.md`` and enforces the ledger's integrity invariants so a
green test suite cannot silently drift from the parity claims:

1. Every requirement row has a status drawn from the allowed vocabulary.
2. Requirement IDs are unique.
3. Every data row under a requirement-table header has exactly the header's
   column count, so a stray ``|`` inside a cell fails loudly instead of
   silently shifting columns.
4. Every ``verified`` row names at least one test/eval in its Test/Eval cell
   (a non-empty value that is not just an em dash). This is the rule PLAN.md
   requires: "CI must fail if a row is marked ``verified`` without evidence."
5. The evidence is real: each backtick-quoted file reference in a
   ``verified`` row's Test/Eval cell (a path, glob, or pytest nodeid such as
   ``tests/test_foo.py::test_bar``) must resolve to an existing file under
   the repo root, and a nodeid's test function must be defined in that file.
   At least one reference per ``verified`` row must be checkable this way.

Run as ``python -m evaluations.parity_check`` (exit 0 clean, 1 on violation)
or import :func:`check_parity` for tests. The parser is deliberately simple
and dependency-free: it reads Markdown pipe tables whose header row contains
``ID`` and ``Status`` columns, so the ledger stays human-editable without a
database.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
import sys

# The status vocabulary is a hard contract shared with docs/PARITY.md. Keep in
# sync with the comment block at the top of that file.
ALLOWED_STATUSES = frozenset(
    {"missing", "partial", "verified", "external", "undisclosed"}
)

# Cells that count as "no evidence provided": empty or a lone em/en dash.
# The en dash is matched deliberately, not a typo for a hyphen.
_EMPTY_CELLS = frozenset({"", "-", "--", "—", "–"})  # noqa: RUF001

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_DEFAULT_LEDGER = _REPO_ROOT / "docs" / "PARITY.md"

# Evidence references are backtick-quoted in the Test/Eval cell.
_BACKTICK_RE = re.compile(r"`([^`]+)`")


@dataclasses.dataclass(frozen=True)
class Row:
    """One parsed requirement row from the ledger."""

    req_id: str
    status: str
    test_eval: str
    source_line: int


@dataclasses.dataclass
class CheckResult:
    """Outcome of a parity check: parsed rows plus any violations."""

    rows: list[Row]
    errors: list[str]

    @property
    def ok(self) -> bool:
        """True when no invariant was violated."""
        return not self.errors

    def status_counts(self) -> dict[str, int]:
        """Return a count of rows per status, for the summary line."""
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row.status] = counts.get(row.status, 0) + 1
        return counts


def _split_pipe_row(line: str) -> list[str] | None:
    """Split a Markdown table line into trimmed cells, or None if not a row.

    A table row starts (after leading whitespace) with ``|``. Leading and
    trailing empty cells produced by the border pipes are dropped.

    Args:
        line: A single raw line from the ledger.

    Returns:
        The list of cell strings, or None when ``line`` is not a pipe row.
    """
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    # Split on the pipe and drop the empty first/last produced by the borders.
    cells = [cell.strip() for cell in stripped.split("|")]
    return cells[1:-1] if len(cells) >= 2 else []


def _is_separator_row(cells: list[str]) -> bool:
    """True when every cell is a Markdown header separator like ``---``."""
    return bool(cells) and all(
        set(cell) <= {"-", ":"} and "-" in cell for cell in cells
    )


def _header_indexes(cells: list[str]) -> tuple[int, int, int, int] | None:
    """Return (id, status, test/eval, residual) column indexes for a header.

    Args:
        cells: The trimmed cells of a candidate header row.

    Returns:
        The four column indexes, or None if this is not a recognizable
        requirement-table header (must have ID and Status columns). The
        residual index is -1 when the header has no residual/gap column.
    """
    lowered = [cell.lower() for cell in cells]
    if "id" not in lowered or "status" not in lowered:
        return None
    id_idx = lowered.index("id")
    status_idx = lowered.index("status")
    # The evidence column is titled "Test/Eval"; match leniently.
    test_idx = next((i for i, cell in enumerate(lowered) if "test" in cell), -1)
    # The last column is the "Residual gap / owner"; match on either word.
    residual_idx = next(
        (i for i, cell in enumerate(lowered) if "residual" in cell), -1
    )
    return id_idx, status_idx, test_idx, residual_idx


def _cell_is_empty(cell: str) -> bool:
    """True when a Test/Eval cell provides no real evidence reference."""
    return cell.strip() in _EMPTY_CELLS


def _looks_like_path(token: str) -> bool:
    """True when a backticked token should be treated as a file reference.

    File references contain a ``/`` and no whitespace; everything else in the
    cell (identifiers, commands like ``python -m evaluations.smoke``, prose)
    is descriptive and not checked.

    Args:
        token: The path part of a backticked token (nodeid suffix removed).

    Returns:
        Whether the token is a checkable repo-relative file reference.
    """
    return "/" in token and not any(ch.isspace() for ch in token)


def _test_defined_in(file_path: pathlib.Path, test_name: str) -> bool:
    """True when ``test_name`` looks defined inside a cited test file.

    Only Python files are checked (``def <name>(`` covers plain and async
    test functions); nodeids citing other file types pass on existence alone.

    Args:
        file_path: The existing evidence file on disk.
        test_name: The test function name from the ``::`` nodeid suffix.

    Returns:
        Whether the named test appears to be defined in the file.
    """
    if file_path.suffix != ".py":
        return True
    text = file_path.read_text(encoding="utf-8")
    return f"def {test_name}(" in text


def _evidence_errors(
    source: str,
    lineno: int,
    req_id: str,
    cell: str,
    repo_root: pathlib.Path,
) -> list[str]:
    """Validate the cited evidence of one ``verified`` row.

    Extracts every backtick-quoted reference from the Test/Eval cell and
    checks the ones that look like file references: plain paths and pytest
    nodeids must point at an existing file (with the named test defined for
    ``.py`` files), globs must match at least one file, and a bare
    ``::test_name`` continuation is resolved against the previously cited
    file. A ``verified`` row must yield at least one such checkable
    reference.

    Args:
        source: The ledger file name, for error prefixes.
        lineno: The row's 1-based line number in the ledger.
        req_id: The requirement ID of the row.
        cell: The raw Test/Eval cell text.
        repo_root: Directory that relative evidence paths resolve against.

    Returns:
        Human-readable error strings (empty when the evidence checks out).
    """
    prefix = f"{source}:{lineno}: {req_id!r}"
    errors: list[str] = []
    checked = 0
    last_file: pathlib.Path | None = None

    for raw in _BACKTICK_RE.findall(cell):
        token = raw.strip()
        if token.startswith("::"):
            # Continuation nodeid: another test in the last cited file.
            if last_file is None:
                continue
            name = token[2:]
            if _test_defined_in(last_file, name):
                checked += 1
            else:
                errors.append(
                    f"{prefix} cites test {name!r} which is not defined "
                    f"in {last_file.relative_to(repo_root)}"
                )
            continue
        path_part, _, test_name = token.partition("::")
        if not _looks_like_path(path_part):
            continue
        if "*" in path_part:
            if any(repo_root.glob(path_part)):
                checked += 1
            else:
                errors.append(
                    f"{prefix} cites evidence glob {path_part!r} which "
                    f"matches no files under the repo root"
                )
            continue
        file_path = repo_root / path_part
        if not file_path.is_file():
            errors.append(
                f"{prefix} cites evidence file {path_part!r} which does "
                f"not exist under the repo root"
            )
            continue
        checked += 1
        last_file = file_path
        if test_name and not _test_defined_in(file_path, test_name):
            errors.append(
                f"{prefix} cites test {test_name!r} which is not defined "
                f"in {path_part}"
            )

    if checked == 0 and not errors:
        errors.append(
            f"{prefix} is 'verified' but its Test/Eval cell contains no "
            f"checkable file reference (expected a backticked path, glob, "
            f"or pytest nodeid relative to the repo root)"
        )
    return errors


def check_parity(
    ledger_path: pathlib.Path | str = _DEFAULT_LEDGER,
    repo_root: pathlib.Path | str = _REPO_ROOT,
) -> CheckResult:
    """Parse the ledger and collect any invariant violations.

    Args:
        ledger_path: Path to the PARITY.md file to check.
        repo_root: Directory that cited evidence paths resolve against.

    Returns:
        A :class:`CheckResult` with every parsed row and a list of
        human-readable error strings (empty when the ledger is clean).
    """
    path = pathlib.Path(ledger_path)
    root = pathlib.Path(repo_root)
    text = path.read_text(encoding="utf-8")

    rows: list[Row] = []
    errors: list[str] = []
    seen_ids: dict[str, int] = {}
    header: tuple[int, int, int, int] | None = None
    expected_cols = 0

    for lineno, line in enumerate(text.splitlines(), start=1):
        cells = _split_pipe_row(line)
        if cells is None:
            continue
        if _is_separator_row(cells):
            continue
        maybe_header = _header_indexes(cells)
        if maybe_header is not None:
            header = maybe_header
            expected_cols = len(cells)
            continue
        if header is None:
            continue
        id_idx, status_idx, test_idx, residual_idx = header
        # A misaligned row means a literal pipe inside a cell (or a missing
        # cell) silently shifted columns — fail loudly instead of misparsing.
        if len(cells) != expected_cols:
            errors.append(
                f"{path.name}:{lineno}: row starting {cells[0]!r} has "
                f"{len(cells)} columns, expected {expected_cols} (a literal "
                f"'|' inside a cell?)"
            )
            continue
        req_id = cells[id_idx].strip("` ")
        status = cells[status_idx].strip().lower()
        test_eval = cells[test_idx].strip() if test_idx >= 0 else ""
        residual = cells[residual_idx].strip() if residual_idx >= 0 else ""
        if not req_id or status not in ALLOWED_STATUSES:
            # Not a requirement row (e.g. a legend/notes table); skip quietly
            # unless it looks like one with a bad status.
            if req_id and status and status not in ALLOWED_STATUSES:
                errors.append(
                    f"{path.name}:{lineno}: row {req_id!r} has unknown status "
                    f"{status!r} (allowed: {sorted(ALLOWED_STATUSES)})"
                )
            continue

        rows.append(Row(req_id, status, test_eval, lineno))

        if req_id in seen_ids:
            errors.append(
                f"{path.name}:{lineno}: duplicate requirement ID {req_id!r} "
                f"(first seen at line {seen_ids[req_id]})"
            )
        else:
            seen_ids[req_id] = lineno

        if status == "verified":
            if _cell_is_empty(test_eval):
                errors.append(
                    f"{path.name}:{lineno}: {req_id!r} is 'verified' but "
                    f"names no test/eval evidence (Test/Eval cell is empty)"
                )
            else:
                errors.extend(
                    _evidence_errors(path.name, lineno, req_id, test_eval, root)
                )

        # A 'partial'/'missing' row must record what remains and who owns it.
        # Downgrading a claim without naming the residual gap is the exact
        # truth-drift the ledger exists to prevent (PLAN.md M0).
        if status in ("partial", "missing") and _cell_is_empty(residual):
            errors.append(
                f"{path.name}:{lineno}: {req_id!r} is {status!r} but records "
                f"no residual gap / owner (the Residual gap cell is empty)"
            )

    if not rows:
        errors.append(f"{path.name}: no requirement rows parsed")

    return CheckResult(rows=rows, errors=errors)


def main(argv: list[str] | None = None) -> int:
    """CLI entry: print a summary and return a process exit code.

    Args:
        argv: Optional argument list; ``argv[0]`` may override the ledger path.

    Returns:
        0 when the ledger passes, 1 on any violation.
    """
    args = argv if argv is not None else sys.argv[1:]
    ledger = pathlib.Path(args[0]) if args else _DEFAULT_LEDGER
    result = check_parity(ledger)

    counts = result.status_counts()
    summary = ", ".join(f"{k}={counts[k]}" for k in sorted(counts))
    print(f"parity: {len(result.rows)} requirement rows ({summary})")

    if result.errors:
        print(f"parity: {len(result.errors)} violation(s):", file=sys.stderr)
        for err in result.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(
        "parity: OK — every 'verified' row cites test/eval evidence that "
        "exists on disk"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
