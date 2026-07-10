"""Tests for the parity-ledger checker.

Covers the invariants PLAN.md requires the checker to enforce (a ``verified``
row must cite evidence that exists on disk; statuses are constrained; IDs
unique; rows keep their header's column count) and confirms the committed
``docs/PARITY.md`` passes its own checker.
"""

from __future__ import annotations

import pathlib
import textwrap

from evaluations import parity_check

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_LEDGER = _REPO_ROOT / "docs" / "PARITY.md"

_HEADER = (
    "\n| ID | Source | Required behavior | Implementation evidence "
    "| Test/Eval | Status | Residual gap |\n"
    "|---|---|---|---|---|---|---|\n"
)


def _write(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    """Write a ledger fragment to a temp file and return its path."""
    path = tmp_path / "PARITY.md"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def _write_rows(tmp_path: pathlib.Path, *rows: str) -> pathlib.Path:
    """Write a ledger with the standard header plus the given rows."""
    return _write(tmp_path, _HEADER + "\n".join(rows) + "\n")


def _add_evidence_file(
    tmp_path: pathlib.Path, rel_path: str, content: str = ""
) -> None:
    """Create a fake evidence file under the temp repo root."""
    target = tmp_path / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_committed_ledger_passes_its_own_checker() -> None:
    """The real docs/PARITY.md must satisfy every invariant."""
    result = parity_check.check_parity(_LEDGER)
    assert result.ok, "\n".join(result.errors)
    # Sanity: the ledger has a meaningful number of requirement rows.
    assert len(result.rows) >= 30


def test_verified_row_without_evidence_fails(tmp_path: pathlib.Path) -> None:
    """A 'verified' row whose Test/Eval cell is an em dash is rejected."""
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | does a thing | code here | — | verified | — |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert not result.ok
    assert any("names no test/eval" in e for e in result.errors)


def test_verified_row_with_existing_evidence_passes(
    tmp_path: pathlib.Path,
) -> None:
    """A 'verified' row citing a nodeid whose file and test exist passes."""
    _add_evidence_file(
        tmp_path, "tests/test_foo.py", "def test_it() -> None:\n    pass\n"
    )
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | does a thing | code |"
        " `tests/test_foo.py::test_it` | verified | — |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert result.ok, result.errors


def test_verified_row_citing_missing_file_fails(
    tmp_path: pathlib.Path,
) -> None:
    """A 'verified' row citing a nonexistent evidence file is rejected."""
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | does a thing | code |"
        " `tests/test_gone.py::test_it` | verified | — |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert not result.ok
    assert any(
        "'tests/test_gone.py' which does not exist" in e for e in result.errors
    )
    assert any("'FOO-001'" in e for e in result.errors)


def test_verified_row_citing_missing_test_name_fails(
    tmp_path: pathlib.Path,
) -> None:
    """A nodeid whose file exists but lacks the named test is rejected."""
    _add_evidence_file(
        tmp_path, "tests/test_foo.py", "def test_other() -> None:\n    pass\n"
    )
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | does a thing | code |"
        " `tests/test_foo.py::test_it` | verified | — |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert not result.ok
    assert any(
        "cites test 'test_it' which is not defined" in e for e in result.errors
    )


def test_continuation_nodeid_checked_against_previous_file(
    tmp_path: pathlib.Path,
) -> None:
    """A bare `::name` token is resolved against the last cited file."""
    _add_evidence_file(
        tmp_path, "tests/test_foo.py", "def test_a() -> None:\n    pass\n"
    )
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | does a thing | code |"
        " `tests/test_foo.py::test_a`, `::test_b` | verified | — |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert not result.ok
    assert any(
        "cites test 'test_b' which is not defined" in e for e in result.errors
    )


def test_verified_row_with_matching_glob_passes(
    tmp_path: pathlib.Path,
) -> None:
    """A glob reference passes when it matches at least one file."""
    _add_evidence_file(tmp_path, "evals/tests/test_x.py")
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | does a thing | code |"
        " `evals/tests/*` (24 tests) | verified | — |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert result.ok, result.errors


def test_verified_row_with_empty_glob_fails(tmp_path: pathlib.Path) -> None:
    """A glob reference matching nothing under the repo root is rejected."""
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | does a thing | code |"
        " `evals/tests/*` | verified | — |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert not result.ok
    assert any("matches no files" in e for e in result.errors)


def test_verified_row_with_only_prose_evidence_fails(
    tmp_path: pathlib.Path,
) -> None:
    """A non-empty cell with no checkable file reference is rejected."""
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | does a thing | code |"
        " manual inspection, `INITIAL_ELO_RATING` | verified | — |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert not result.ok
    assert any("no checkable file reference" in e for e in result.errors)


def test_row_with_shifted_columns_fails(tmp_path: pathlib.Path) -> None:
    """A literal pipe inside a cell fails loudly instead of misparsing."""
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | does a | b thing | code | t | partial | — |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert not result.ok
    assert any(
        "has 8 columns, expected 7" in e and "'FOO-001'" in e
        for e in result.errors
    )


def test_row_with_missing_column_fails(tmp_path: pathlib.Path) -> None:
    """A row with too few cells is reported, not silently skipped."""
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | does a thing | code | t | partial |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert not result.ok
    assert any("has 6 columns, expected 7" in e for e in result.errors)


def test_unknown_status_is_rejected(tmp_path: pathlib.Path) -> None:
    """A status outside the allowed vocabulary is an error."""
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | does a thing | code | — | done | — |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert not result.ok
    assert any("unknown status" in e for e in result.errors)


def test_duplicate_ids_are_rejected(tmp_path: pathlib.Path) -> None:
    """Two rows with the same ID are flagged."""
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | a | code | t | partial | — |",
        "| FOO-001 | PAPER | b | code | t | missing | — |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert not result.ok
    assert any("duplicate requirement ID" in e for e in result.errors)


def test_partial_and_missing_rows_need_no_evidence(
    tmp_path: pathlib.Path,
) -> None:
    """Only 'verified' requires evidence; other statuses may leave it empty."""
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | a | code | — | partial | owner |",
        "| FOO-002 | PAPER | b | code | — | missing | owner |",
        "| FOO-003 | PAPER | c | none | — | external | blocker |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert result.ok, result.errors
    assert result.status_counts() == {
        "partial": 1,
        "missing": 1,
        "external": 1,
    }


def test_main_returns_nonzero_on_violation(tmp_path: pathlib.Path) -> None:
    """The CLI entry returns 1 when the ledger has a violation."""
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | a | code | — | verified | — |",
    )
    assert parity_check.main([str(ledger)]) == 1


def test_main_returns_zero_on_clean_ledger() -> None:
    """The CLI entry returns 0 for the committed ledger."""
    assert parity_check.main([str(_LEDGER)]) == 0
