"""Store tests for per-run execution metrics persistence."""

from __future__ import annotations

from app import store

_METRICS = {
    "total_time": 12.5,
    "hypothesis_count": 8,
    "reviews_count": 8,
    "tournaments_count": 6,
    "evolutions_count": 2,
    "llm_calls": 24,
    "phase_times": {"generate": 4.0, "ranking": 2.5},
}


def _make_run(db_path: str) -> str:
    run = store.create_run(
        "Metrics goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(db_path=db_path),
    )
    return run.id


def test_metrics_roundtrip(isolated_db: str) -> None:
    run_id = _make_run(isolated_db)
    store.save_run_metrics(run_id, _METRICS, db_path=isolated_db)
    assert store.get_run_metrics(run_id, db_path=isolated_db) == _METRICS


def test_metrics_absent_returns_none(isolated_db: str) -> None:
    run_id = _make_run(isolated_db)
    assert store.get_run_metrics(run_id, db_path=isolated_db) is None


def test_metrics_upsert_replaces_previous_row(isolated_db: str) -> None:
    run_id = _make_run(isolated_db)
    store.save_run_metrics(run_id, _METRICS, db_path=isolated_db)
    replacement = {**_METRICS, "llm_calls": 99}
    store.save_run_metrics(run_id, replacement, db_path=isolated_db)
    saved = store.get_run_metrics(run_id, db_path=isolated_db)
    assert saved is not None
    assert saved["llm_calls"] == 99


def test_clear_run_derived_data_removes_metrics(isolated_db: str) -> None:
    """A resume's derived-data wipe drops metrics; re-finalize rewrites them."""
    run_id = _make_run(isolated_db)
    store.save_run_metrics(run_id, _METRICS, db_path=isolated_db)
    store.clear_run_derived_data(run_id, db_path=isolated_db)
    assert store.get_run_metrics(run_id, db_path=isolated_db) is None
