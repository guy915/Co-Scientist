"""Pre-tournament per-hypothesis safety screening (Milestone 6 / M9 wiring).

Covers ``app.hypothesis.screening.screen_hypotheses``: it must persist every
hypothesis's ``safety_status``, flag the blocking ones, record an audit row for
each block, and leave benign hypotheses eligible.
"""

from __future__ import annotations

from app import store
from app.hypothesis.screening import (
    ScreeningResult,
    hypothesis_text,
    screen_hypotheses,
)
from tests._store_helpers import _add


def test_screen_persists_status_and_blocks_unsafe(isolated_db: str) -> None:
    run = store.create_run("safety goal", "standard", "mock", {})
    safe_id = _add(
        run.id,
        "Safe",
        "Inhibiting kinase X reduces AML tumor growth via apoptosis.",
        isolated_db,
    )
    unsafe_id = _add(
        run.id,
        "Unsafe",
        "Weaponize the pathogen to enhance transmissibility in humans.",
        isolated_db,
    )

    result = screen_hypotheses(
        run.id, store.list_hypotheses(run.id), db_path=isolated_db
    )

    assert isinstance(result, ScreeningResult)
    # The unsafe hypothesis is blocked; the safe one is not.
    assert result.blocked_ids == frozenset({unsafe_id})
    assert result.status_by_id[safe_id] == "allow"
    assert result.status_by_id[unsafe_id] == "prohibited"
    assert result.screened_count == 2
    assert result.blocked_count == 1

    # The status is persisted on the store row.
    by_id = {h["id"]: h for h in store.list_hypotheses(run.id)}
    assert by_id[safe_id]["safety_status"] == "allow"
    assert by_id[unsafe_id]["safety_status"] == "prohibited"

    # Exactly one blocking audit row, for the unsafe hypothesis.
    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    blocks = [d for d in decisions if d["stage"] == "hypothesis"]
    assert len(blocks) == 1
    assert unsafe_id in blocks[0]["reason"]


def test_screen_flags_mechanism_not_just_statement(isolated_db: str) -> None:
    """A benign statement with an unsafe mechanism is still caught."""
    run = store.create_run("safety goal", "standard", "mock", {})
    hyp_id = _add(
        run.id,
        "Benign headline",
        "A novel therapeutic approach for a viral disease.",
        isolated_db,
        mechanism="The route is to weaponize the agent for mass-casualty use.",
    )

    result = screen_hypotheses(
        run.id, store.list_hypotheses(run.id), db_path=isolated_db
    )

    assert hyp_id in result.blocked_ids


def test_screen_redacts_detail_fields_of_redact_outcome(
    isolated_db: str,
) -> None:
    """A REDACT hypothesis stays rankable but its detail fields are redacted."""
    from app.hypothesis.safety import REDACTED_PLACEHOLDER

    run = store.create_run("safety goal", "standard", "mock", {})
    hyp_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Sensitive detail",
            statement="A therapeutic approach for a viral disease.",
            mechanism="A step-by-step synthesis protocol for the compound.",
            experimental_context="Follow the synthesis route in a BSL-2 lab.",
        ),
        db_path=isolated_db,
    )
    payloads = store.list_hypotheses(run.id)

    result = screen_hypotheses(run.id, payloads, db_path=isolated_db)

    # Redacting outcomes do not block the tournament.
    assert hyp_id not in result.blocked_ids
    assert result.status_by_id[hyp_id] == "redact"

    # The persisted detail fields are redacted; the statement is untouched.
    row = store.get_hypothesis(hyp_id, db_path=isolated_db)
    assert row is not None
    assert row["mechanism"] == REDACTED_PLACEHOLDER
    assert row["experimental_context"] == REDACTED_PLACEHOLDER
    assert row["statement"] == "A therapeutic approach for a viral disease."

    # The in-memory payload is mutated too, so event stubs see the redaction.
    assert payloads[0]["mechanism"] == REDACTED_PLACEHOLDER

    # A redact audit row is recorded.
    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    redactions = [d for d in decisions if d["decision"] == "redact"]
    assert len(redactions) == 1
    assert hyp_id in redactions[0]["reason"]


def test_rescreen_does_not_downgrade_a_redacted_hypothesis(
    isolated_db: str,
) -> None:
    """Re-screening a redacted hypothesis keeps `redact`, not `allow`.

    The first pass redacts the mechanism; a second pass over the (now
    redacted) pool must not read ALLOW off the wiped text and downgrade the
    recorded status. This is the exact re-screen that fires when a scientist
    adds an input to a run.
    """
    run = store.create_run("safety goal", "standard", "mock", {})
    store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Sensitive detail",
            statement="A therapeutic approach.",
            mechanism="A step-by-step synthesis protocol.",
        ),
        db_path=isolated_db,
    )

    first = screen_hypotheses(
        run.id, store.list_hypotheses(run.id), db_path=isolated_db
    )
    (hyp_id,) = first.status_by_id
    assert first.status_by_id[hyp_id] == "redact"

    # Second pass over the redacted pool preserves the status.
    second = screen_hypotheses(
        run.id, store.list_hypotheses(run.id), db_path=isolated_db
    )
    assert second.status_by_id[hyp_id] == "redact"
    row = store.get_hypothesis(hyp_id, db_path=isolated_db)
    assert row is not None and row["safety_status"] == "redact"

    # No duplicate redact audit row from the second pass.
    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    assert len([d for d in decisions if d["decision"] == "redact"]) == 1


def test_hypothesis_text_combines_fields() -> None:
    text = hypothesis_text(
        {
            "statement": "s",
            "mechanism": "m",
            "expected_effect": "e",
            "experimental_context": "c",
        }
    )
    assert text == "s\nm\ne\nc"
