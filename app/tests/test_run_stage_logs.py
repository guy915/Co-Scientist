"""Tests for mirroring run stage events into the persisted app log.

Every ``run_events`` row is echoed as a compact ``app.run_stage`` record
so the run's stage narrative (generate, reflection, ranking, ...) is
visible from the Logs panel and ``cosci logs`` — the event stream itself
is only reachable over SSE.
"""

from __future__ import annotations

import logging

import pytest

from app import store


def _stage_records(
    caplog: pytest.LogCaptureFixture,
) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.run_stage"]


@pytest.fixture
def run_id(isolated_db: str) -> str:
    """A real run id: run_events has a foreign key to runs."""
    run = store.create_run(
        "stage logging",
        "standard",
        "mock",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    return str(run.id)


def test_append_event_logs_a_compact_stage_record(
    isolated_db: str, run_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        store.append_event(
            run_id, "generate", {"count": 4}, db_path=isolated_db
        )
    records = _stage_records(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == "generate count=4 activity=drafting"
    # Run-scoped so `cosci logs --run <id>` and the run-scoped endpoint
    # pick it up even outside a run_log_context.
    assert getattr(records[0], "run_id", None) == run_id


def test_stage_record_summarizes_bulky_payloads(
    isolated_db: str, run_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    payload = {
        "count": 4,
        # Bulk collections are reduced to their size: the whole point is
        # that reading logs must not cost what reading the event does.
        "hypotheses": [{"id": "h1", "text": "x" * 500}] * 4,
        "clusters": {"cluster-0": 2, "cluster-1": 1},
        "critique": "y" * 400,
    }
    with caplog.at_level(logging.INFO):
        store.append_event(run_id, "generate", payload, db_path=isolated_db)
    message = _stage_records(caplog)[0].getMessage()
    assert "count=4" in message
    assert "hypotheses=4" in message
    assert "clusters=2" in message
    assert "x" * 100 not in message
    assert len(message) <= 200


def test_stage_record_truncates_at_a_pair_boundary(
    isolated_db: str, run_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    payload = {f"key{i}": "v" * 20 for i in range(20)}
    with caplog.at_level(logging.INFO):
        store.append_event(run_id, "report", payload, db_path=isolated_db)
    message = _stage_records(caplog)[0].getMessage()
    assert len(message) <= 200
    # A dangling half-pair reads like a key whose value went missing;
    # drop whole pairs and mark the cut instead.
    assert message.endswith("...")
    for part in message.removesuffix(" ...").split(" ")[1:]:
        assert "=" in part, part


def test_stage_record_keeps_useful_scalars(
    isolated_db: str, run_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        store.append_event(
            run_id,
            "safety.intake",
            {"stage": "intake", "decision": "allow", "reason": ""},
            db_path=isolated_db,
        )
        store.append_event(
            run_id,
            "ranking",
            {"iteration": 2, "matches": [1, 2, 3]},
            db_path=isolated_db,
        )
    messages = [r.getMessage() for r in _stage_records(caplog)]
    assert messages[0] == (
        "safety.intake stage=intake decision=allow activity=safety"
    )
    assert messages[1] == "ranking iteration=2 matches=3 activity=tournament"


def test_events_written_inside_transactions_are_logged(
    isolated_db: str, run_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    store.update_run_status(
        run_id, store.RunStatus.RUNNING, db_path=isolated_db
    )
    with caplog.at_level(logging.INFO):
        # Startup reconciliation appends its status event through the
        # inner (open-connection) writer, so covering it proves both
        # event write paths mirror, not just the standalone one.
        store.reconcile_interrupted_runs(db_path=isolated_db)
    messages = [r.getMessage() for r in _stage_records(caplog)]
    assert any("status=failed" in m for m in messages), messages


def test_stage_logging_never_breaks_the_event_write(
    isolated_db: str, run_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("logging is down")

    monkeypatch.setattr("app.store.events._log_stage", boom)
    # The event log is the canonical timeline; mirroring it into the
    # app log must never be able to take that write down.
    seq = store.append_event(
        run_id, "generate", {"count": 1}, db_path=isolated_db
    )
    assert seq >= 1
    assert len(store.list_events(run_id, db_path=isolated_db)) == 1
