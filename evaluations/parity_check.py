"""Parity-ledger checker.

Parses ``docs/PARITY.md`` and enforces the ledger's integrity invariants so a
green test suite cannot silently drift from the parity claims:

1. Every requirement row has a status drawn from the allowed vocabulary
   (``missing``, ``partial``, ``verified``, ``external``, ``undisclosed``,
   ``divergent`` — the last being a deliberate, accepted difference from
   Google that the project has decided not to change).
2. Requirement IDs are unique.
3. Every data row under a requirement-table header has exactly the header's
   column count, so a stray ``|`` inside a cell fails loudly instead of
   silently shifting columns.
4. Every ``verified`` row names at least one test/eval in its Test/Eval cell
   (a non-empty value that is not just an em dash). The rule: CI must fail if
   a row is marked ``verified`` without evidence.
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

import ast
import dataclasses
import pathlib
import re
import sys

# The status vocabulary is a hard contract shared with docs/PARITY.md. Keep in
# sync with the comment block at the top of that file.
ALLOWED_STATUSES = frozenset(
    {"missing", "partial", "verified", "external", "undisclosed", "divergent"}
)

# Cells that count as "no evidence provided": empty or a lone em/en dash.
# The en dash is matched deliberately, not a typo for a hyphen.
_EMPTY_CELLS = frozenset({"", "-", "--", "—", "–"})  # noqa: RUF001

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_DEFAULT_LEDGER = _REPO_ROOT / "docs" / "PARITY.md"

# Evidence references are backtick-quoted in the Test/Eval cell.
_BACKTICK_RE = re.compile(r"`([^`]+)`")


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
    """Check a function or class-qualified pytest name in a cited file.

    Python nodeids may name a top-level function or a class-scoped test.
    Other file types pass on existence alone.

    Args:
        file_path: The existing evidence file on disk.
        test_name: The test function name from the ``::`` nodeid suffix.

    Returns:
        Whether the named test appears to be defined in the file.
    """
    if file_path.suffix != ".py":
        return True
    nodes = ast.parse(file_path.read_text(encoding="utf-8")).body
    definition: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | None
    definition = None
    for part in test_name.split("::"):
        definition = next(
            (
                node
                for node in nodes
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                )
                and node.name == part
            ),
            None,
        )
        if definition is None:
            return False
        nodes = definition.body
    return isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef))


def _check_continuation_token(
    prefix: str,
    token: str,
    last_file: pathlib.Path | None,
    repo_root: pathlib.Path,
) -> tuple[int, list[str]]:
    """Check a bare ``::test_name`` token against the last cited file.

    Args:
        prefix: The ``file:line: id`` error prefix for this row.
        token: The backticked token, starting with ``::``.
        last_file: The previously cited evidence file, if any.
        repo_root: Directory that relative evidence paths resolve against.

    Returns:
        A ``(checked_increment, errors)`` pair.
    """
    if last_file is None:
        return 0, []
    name = token[2:]
    if _test_defined_in(last_file, name):
        return 1, []
    return 0, [
        f"{prefix} cites test {name!r} which is not defined "
        f"in {last_file.relative_to(repo_root)}"
    ]


def _check_glob_token(
    prefix: str, path_part: str, repo_root: pathlib.Path
) -> tuple[int, list[str]]:
    """Check a glob evidence token against the repo root."""
    if any(repo_root.glob(path_part)):
        return 1, []
    return 0, [
        f"{prefix} cites evidence glob {path_part!r} which "
        f"matches no files under the repo root"
    ]


def _check_path_token(
    prefix: str,
    token: str,
    repo_root: pathlib.Path,
) -> tuple[int, pathlib.Path | None, list[str]]:
    """Check one path/glob/nodeid token from a Test/Eval cell.

    Returns a ``(checked_increment, cited_file, errors)`` triple;
    ``cited_file`` is the resolved evidence file when the token named
    one directly.
    """
    path_part, _, test_name = token.partition("::")
    if not _looks_like_path(path_part):
        return 0, None, []
    if "*" in path_part:
        found, glob_errors = _check_glob_token(prefix, path_part, repo_root)
        return found, None, glob_errors
    file_path = repo_root / path_part
    if not file_path.is_file():
        return (
            0,
            None,
            [
                f"{prefix} cites evidence file {path_part!r} which does "
                f"not exist under the repo root"
            ],
        )
    errors: list[str] = []
    if test_name and not _test_defined_in(file_path, test_name):
        errors.append(
            f"{prefix} cites test {test_name!r} which is not defined "
            f"in {path_part}"
        )
    return 1, file_path, errors


def _evidence_errors(
    source: str,
    lineno: int,
    req_id: str,
    cell: str,
    repo_root: pathlib.Path,
) -> list[str]:
    """Validate the cited evidence of one ``verified`` row.

    Checks every backtick-quoted reference that looks like a file
    reference (path, glob, or pytest nodeid; a bare ``::test_name``
    continues the previously cited file). A ``verified`` row must yield
    at least one checkable reference. Returns human-readable error
    strings (empty when the evidence checks out).
    """
    prefix = f"{source}:{lineno}: {req_id!r}"
    errors: list[str] = []
    checked = 0
    last_file: pathlib.Path | None = None

    for raw in _BACKTICK_RE.findall(cell):
        token = raw.strip()
        if token.startswith("::"):
            found, errs = _check_continuation_token(
                prefix, token, last_file, repo_root
            )
        else:
            found, cited, errs = _check_path_token(prefix, token, repo_root)
            if cited is not None:
                last_file = cited
        checked += found
        errors.extend(errs)

    if checked == 0 and not errors:
        errors.append(
            f"{prefix} is 'verified' but its Test/Eval cell contains no "
            f"checkable file reference (expected a backticked path, glob, "
            f"or pytest nodeid relative to the repo root)"
        )
    return errors


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


@dataclasses.dataclass(frozen=True)
class _ParsedRow:
    """The four contract-bearing cells of one requirement row.

    Attributes:
        req_id: Requirement identifier from the ID column.
        status: Lowercased status cell (one of ``ALLOWED_STATUSES``).
        test_eval: Raw Test/Eval cell, which cites evidence.
        residual: Raw Residual-gap cell.
    """

    req_id: str
    status: str
    test_eval: str
    residual: str


def _row_status_errors(
    source: str,
    lineno: int,
    parsed: _ParsedRow,
    root: pathlib.Path,
) -> list[str]:
    """Return violations of one requirement row's status contract."""
    errors: list[str] = []
    if parsed.status == "verified":
        if _cell_is_empty(parsed.test_eval):
            errors.append(
                f"{source}:{lineno}: {parsed.req_id!r} is 'verified' but "
                f"names no test/eval evidence (Test/Eval cell is empty)"
            )
        else:
            errors.extend(
                _evidence_errors(
                    source, lineno, parsed.req_id, parsed.test_eval, root
                )
            )

    # A 'partial'/'missing'/'divergent' row must record what remains (or, for
    # 'divergent', why the difference is accepted) and who owns it. Downgrading
    # a claim without naming the residual gap is the exact truth-drift the
    # ledger exists to prevent.
    if parsed.status in ("partial", "missing", "divergent") and _cell_is_empty(
        parsed.residual
    ):
        errors.append(
            f"{source}:{lineno}: {parsed.req_id!r} is {parsed.status!r} but "
            f"records no residual gap / owner (the Residual gap cell is "
            f"empty)"
        )
    return errors


def _check_requirement_row(
    source: str,
    lineno: int,
    cells: list[str],
    header: tuple[int, int, int, int],
    root: pathlib.Path,
) -> tuple[Row | None, list[str]]:
    """Parse one aligned data row into a Row plus its violations."""
    id_idx, status_idx, test_idx, residual_idx = header
    req_id = cells[id_idx].strip("` ")
    status = cells[status_idx].strip().lower()
    test_eval = cells[test_idx].strip() if test_idx >= 0 else ""
    residual = cells[residual_idx].strip() if residual_idx >= 0 else ""
    if not req_id or status not in ALLOWED_STATUSES:
        # Not a requirement row (e.g. a legend/notes table); skip quietly
        # unless it looks like one with a bad status.
        if req_id and status and status not in ALLOWED_STATUSES:
            return None, [
                f"{source}:{lineno}: row {req_id!r} has unknown status "
                f"{status!r} (allowed: {sorted(ALLOWED_STATUSES)})"
            ]
        return None, []
    row = Row(req_id, status, test_eval, lineno)
    parsed = _ParsedRow(req_id, status, test_eval, residual)
    return row, _row_status_errors(source, lineno, parsed, root)


@dataclasses.dataclass(frozen=True)
class _TableContext:
    """Per-file context every row of one ledger table shares.

    Attributes:
        source: Ledger file name, used to prefix violation messages.
        header: Column indexes of (ID, Status, Test/Eval, Residual gap).
        expected_cols: Column count every data row must match exactly.
        root: Repo root that cited evidence paths resolve against.
    """

    source: str
    header: tuple[int, int, int, int]
    expected_cols: int
    root: pathlib.Path


def _handle_data_row(
    lineno: int,
    cells: list[str],
    table: _TableContext,
    rows: list[Row],
    seen_ids: dict[str, int],
) -> list[str]:
    """Process one data row, appending to ``rows``; return its violations."""
    source = table.source
    # A misaligned row means a literal pipe inside a cell (or a missing
    # cell) silently shifted columns — fail loudly instead of misparsing.
    if len(cells) != table.expected_cols:
        return [
            f"{source}:{lineno}: row starting {cells[0]!r} has "
            f"{len(cells)} columns, expected {table.expected_cols} (a "
            f"literal '|' inside a cell?)"
        ]
    row, errors = _check_requirement_row(
        source, lineno, cells, table.header, table.root
    )
    if row is None:
        return errors
    rows.append(row)
    if row.req_id in seen_ids:
        errors.append(
            f"{source}:{lineno}: duplicate requirement ID {row.req_id!r} "
            f"(first seen at line {seen_ids[row.req_id]})"
        )
    else:
        seen_ids[row.req_id] = lineno
    return errors


def _parse_ledger_lines(
    source: str, text: str, root: pathlib.Path
) -> tuple[list[Row], list[str]]:
    """Parse every ledger line into rows plus violations."""
    rows: list[Row] = []
    errors: list[str] = []
    seen_ids: dict[str, int] = {}
    header: tuple[int, int, int, int] | None = None
    expected_cols = 0

    for lineno, line in enumerate(text.splitlines(), start=1):
        cells = _split_pipe_row(line)
        if cells is None or _is_separator_row(cells):
            continue
        maybe_header = _header_indexes(cells)
        if maybe_header is not None:
            header = maybe_header
            expected_cols = len(cells)
            continue
        if header is None:
            continue
        errors.extend(
            _handle_data_row(
                lineno,
                cells,
                _TableContext(source, header, expected_cols, root),
                rows,
                seen_ids,
            )
        )
    return rows, errors


def check_parity(
    ledger_path: pathlib.Path | str = _DEFAULT_LEDGER,
    repo_root: pathlib.Path | str = _REPO_ROOT,
) -> CheckResult:
    """Parse the ledger at ``ledger_path`` into a :class:`CheckResult`.

    Cited evidence paths resolve against ``repo_root``.
    """
    path = pathlib.Path(ledger_path)
    root = pathlib.Path(repo_root)
    text = path.read_text(encoding="utf-8")

    rows, errors = _parse_ledger_lines(path.name, text, root)
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
