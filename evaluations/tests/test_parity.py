"""Parity regression tests."""

from __future__ import annotations

import pathlib
import re
import textwrap

import pytest

from evaluations import parity_check

# Parity check.

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


@pytest.mark.parametrize(
    ("nodeid", "valid"),
    [
        ("TestEvidence::test_it", True),
        ("TestMissing::test_it", False),
        ("test_it", False),
    ],
)
def test_class_scoped_evidence_requires_its_owner(
    tmp_path: pathlib.Path, nodeid: str, valid: bool
) -> None:
    _add_evidence_file(
        tmp_path,
        "tests/test_foo.py",
        "class TestEvidence:\n"
        "    async def test_it(self) -> None:\n"
        "        pass\n",
    )
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | does a thing | code | "
        f"`tests/test_foo.py::{nodeid}` | verified | — |",
    )
    assert parity_check.check_parity(ledger, repo_root=tmp_path).ok == valid


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


def test_partial_row_without_residual_gap_fails(
    tmp_path: pathlib.Path,
) -> None:
    """A 'partial' row must record a residual gap / owner.

    Downgrading a row to 'partial' without saying what remains and who owns
    it is exactly the truth-drift the ledger exists to prevent, so an empty
    residual cell is a hard failure.
    """
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | a | code | — | partial | — |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert not result.ok
    assert any("residual" in e.lower() for e in result.errors)


def test_missing_row_without_residual_gap_fails(
    tmp_path: pathlib.Path,
) -> None:
    """A 'missing' row must also name a residual gap / owner."""
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | a | code | — | missing | — |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert not result.ok
    assert any("residual" in e.lower() for e in result.errors)


def test_partial_row_with_residual_gap_passes(
    tmp_path: pathlib.Path,
) -> None:
    """A 'partial' row that records its gap/owner satisfies the checker."""
    ledger = _write_rows(
        tmp_path,
        "| FOO-001 | PAPER | a | code | — | partial |"
        " app persistence owned by M9 |",
    )
    result = parity_check.check_parity(ledger, repo_root=tmp_path)
    assert result.ok, result.errors


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


# Docs truth.

_DOCS = pathlib.Path(__file__).resolve().parent.parent.parent / "docs"
_FIDELITY = _DOCS / "FIDELITY.md"
_ARCHITECTURE = _DOCS / "ARCHITECTURE.md"


def test_ledger_snapshot_matches_checker() -> None:
    """PARITY.md's status snapshot must equal the live checker.

    This is the guard that would have caught the audit's finding: a stale
    ``verified=54, partial=0`` snapshot while the ledger had drifted. The
    snapshot line lists ``status=NN`` pairs and an ``over NN requirement
    rows`` total; both must match ``check_parity`` exactly, so the numbers
    cannot silently rot again.
    """
    result = parity_check.check_parity(_LEDGER)
    counts = result.status_counts()
    text = _LEDGER.read_text(encoding="utf-8")

    # Isolate the snapshot line ("over NN requirement rows: **status=NN, ...**")
    # so historical numbers elsewhere in the prose (e.g. the reclassification
    # note) cannot satisfy or break this check.
    blob = re.search(r"requirement rows:\s*\n?\s*\*\*([^*]+)\*\*", text)
    assert blob is not None, "could not find the status snapshot line"
    snapshot = {
        m.group(1): int(m.group(2))
        for m in re.finditer(
            r"(verified|partial|missing|external|undisclosed|divergent)=(\d+)",
            blob.group(1),
        )
    }
    # Every disclosed status matches the checker...
    for status, disclosed in snapshot.items():
        assert counts.get(status, 0) == disclosed, (
            f"snapshot says {status}={disclosed} but checker counts "
            f"{counts.get(status, 0)}"
        )
    # ...and every status the checker found is disclosed.
    for status, actual in counts.items():
        assert snapshot.get(status) == actual, (
            f"checker has {status}={actual} not disclosed in the snapshot"
        )

    total = re.search(r"over (\d+) requirement rows", text)
    assert total is not None, "snapshot must state the total requirement rows"
    assert int(total.group(1)) == len(result.rows)


def test_fidelity_does_not_claim_citation_is_a_gate() -> None:
    """Citation classification is an audit label, not a verification gate.

    The old FIDELITY row 'Citation verification is a gate, not decoration'
    overclaimed; claim-level verification/gating is Milestone 5.
    """
    text = _FIDELITY.read_text(encoding="utf-8")
    assert "gate, not decoration" not in text
    # The corrected doc names it an audit label explicitly.
    assert "audit label" in text.lower()


def test_fidelity_points_to_parity_ledger() -> None:
    """FIDELITY.md defers to PARITY.md as the authoritative parity record."""
    text = _FIDELITY.read_text(encoding="utf-8")
    assert "PARITY.md" in text


def test_fidelity_reflects_supervisor_is_now_dynamic() -> None:
    """M2 shipped adaptive scheduling; FIDELITY must reflect it, not deny it.

    Guards against the stale claim (from before Milestone 2) that the
    Supervisor does *not yet* dynamically schedule agents — the exact
    doc-drift the parity re-audit flagged.
    """
    # Normalize whitespace so the assertion survives Markdown line wrapping.
    text = " ".join(_FIDELITY.read_text(encoding="utf-8").lower().split())
    assert "not** yet dynamically schedule" not in text
    assert "dynamically schedules" in text


def test_fidelity_does_not_list_retired_tab_components_as_live() -> None:
    """FIDELITY must not present retired tab components as the live UI.

    The only live tab component is ideas_tab; run_detail renders the rest
    inline. The corrected doc names ideas_tab.tsx as the sole live tab.
    """
    text = _FIDELITY.read_text(encoding="utf-8")
    assert "ideas_tab.tsx" in text


def test_fidelity_does_not_deny_implemented_auth() -> None:
    """FIDELITY must not list invite-based researcher auth as out of scope.

    Guards the N26 correction: the doc used to claim "Multi-user
    collaboration, authentication, and project ownership. Local-first
    only." while `app/app/auth.py` and `enforce_run_ownership` already
    implement invite-based auth and per-client run ownership.
    """
    text = _FIDELITY.read_text(encoding="utf-8")
    assert "local-first only" not in text.lower()
    assert "app/app/auth.py" in text


def test_fidelity_does_not_deny_the_durable_worker_queue() -> None:
    """FIDELITY must not describe runs as a bare FastAPI background task.

    Guards the N26 correction: the doc used to claim "Runs execute in a
    FastAPI background task; no Celery/Redis worker pool," omitting the
    durable, leased, resumable task queue (`app/app/store/tasks.py`) that
    actually drives every run. What remains genuinely out of scope is the
    *distributed* (multi-replica) half.
    """
    text = _FIDELITY.read_text(encoding="utf-8")
    assert "runs execute in a fastapi background task" not in text.lower()
    assert "store/tasks.py" in text


def test_architecture_discloses_the_browser_storage_keys() -> None:
    """ARCHITECTURE must not claim the workbench holds no durable state.

    Guards the N26 correction: the doc used to state "The workbench holds
    no durable state in the browser," while `client_id.ts`, `theme_context`,
    `api_key.ts`, and `layout_diagnostics_state.ts`
    persist identity/preference keys to localStorage/sessionStorage.
    """
    text = _ARCHITECTURE.read_text(encoding="utf-8")
    assert "holds no durable state in the browser" not in text
    for key in (
        "co_scientist_client_id",
        "cosci-theme",
        "cosci-api-key",
    ):
        assert key in text, f"missing disclosed storage key: {key}"
