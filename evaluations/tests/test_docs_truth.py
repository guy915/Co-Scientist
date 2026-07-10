"""Docs-truth regression guards (PLAN.md Milestone 0).

These pin the specific documentation-drift corrections made in Milestone 0 so
they cannot silently regress: no doc may describe intended or mock-only
behavior as production-engine behavior. The checks are deliberately narrow —
they assert the *known* false claims stay gone and the truth anchor stays
present, not general prose quality.
"""

from __future__ import annotations

import pathlib

_DOCS = pathlib.Path(__file__).resolve().parent.parent.parent / "docs"
_FIDELITY = _DOCS / "FIDELITY.md"


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


def test_fidelity_flags_supervisor_is_not_yet_dynamic() -> None:
    """The supervisor conditions prompts but is not yet a dynamic scheduler.

    Guards against re-introducing a claim that the Supervisor dynamically
    schedules/weights agents (Milestone 2).
    """
    # Normalize whitespace so the assertion survives Markdown line wrapping.
    text = " ".join(_FIDELITY.read_text(encoding="utf-8").lower().split())
    assert "not** yet dynamically schedule" in text


def test_fidelity_does_not_list_retired_tab_components_as_live() -> None:
    """FIDELITY must not present retired tab components as the live UI.

    The only live tab component is ideas_tab; run_detail renders the rest
    inline. The corrected doc names ideas_tab.tsx as the sole live tab.
    """
    text = _FIDELITY.read_text(encoding="utf-8")
    assert "ideas_tab.tsx" in text
