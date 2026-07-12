"""Docs-truth regression guards (PLAN.md Milestone 0).

These pin the specific documentation-drift corrections made in Milestone 0 so
they cannot silently regress: no doc may describe intended or mock-only
behavior as production-engine behavior. The checks are deliberately narrow —
they assert the *known* false claims stay gone and the truth anchor stays
present, not general prose quality.
"""

from __future__ import annotations

import pathlib
import re

from evaluations import parity_check

_DOCS = pathlib.Path(__file__).resolve().parent.parent.parent / "docs"
_FIDELITY = _DOCS / "FIDELITY.md"
_VERIFICATION = _DOCS / "PARITY-VERIFICATION.md"
_LEDGER = _DOCS / "PARITY.md"


def test_verification_snapshot_matches_checker() -> None:
    """PARITY-VERIFICATION.md's status snapshot must equal the live checker.

    This is the guard that would have caught the audit's finding: a stale
    ``verified=54, partial=0`` snapshot while the ledger had drifted. The
    snapshot line lists ``status=NN`` pairs and an ``over NN requirement
    rows`` total; both must match ``check_parity`` exactly, so the numbers
    cannot silently rot again.
    """
    result = parity_check.check_parity(_LEDGER)
    counts = result.status_counts()
    text = _VERIFICATION.read_text(encoding="utf-8")

    # Isolate the snapshot line ("over NN requirement rows: **status=NN, ...**")
    # so historical numbers elsewhere in the prose (e.g. the reclassification
    # note) cannot satisfy or break this check.
    blob = re.search(r"requirement rows:\s*\n?\s*\*\*([^*]+)\*\*", text)
    assert blob is not None, "could not find the status snapshot line"
    snapshot = {
        m.group(1): int(m.group(2))
        for m in re.finditer(
            r"(verified|partial|missing|external|undisclosed)=(\d+)",
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
