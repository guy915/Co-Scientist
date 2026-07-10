"""Tests for durable workflow-checkpoint persistence (Milestone 4)."""

from __future__ import annotations

from app import store


def _run(db: str) -> str:
    return store.create_run("goal", "standard", "mock", {}, db_path=db).id


def test_save_and_get_latest_checkpoint(isolated_db: str) -> None:
    """Saving checkpoints assigns monotonic seqs; latest is returned."""
    run_id = _run(isolated_db)
    assert store.get_latest_checkpoint(run_id, db_path=isolated_db) is None
    assert not store.has_checkpoint(run_id, db_path=isolated_db)

    seq1 = store.save_checkpoint(
        run_id,
        stage="post_generation",
        schema_version=1,
        last_event_seq=5,
        state={"hyp_ids": ["a", "b"]},
        db_path=isolated_db,
    )
    seq2 = store.save_checkpoint(
        run_id,
        stage="post_ranking",
        schema_version=1,
        last_event_seq=12,
        state={"hyp_ids": ["a", "b"], "round": 1},
        db_path=isolated_db,
    )
    assert (seq1, seq2) == (1, 2)
    assert store.has_checkpoint(run_id, db_path=isolated_db)

    latest = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None
    assert latest["seq"] == 2
    assert latest["stage"] == "post_ranking"
    assert latest["last_event_seq"] == 12
    assert latest["state"] == {"hyp_ids": ["a", "b"], "round": 1}


def test_checkpoints_are_run_scoped(isolated_db: str) -> None:
    """A checkpoint belongs only to its run."""
    run_a = _run(isolated_db)
    run_b = _run(isolated_db)
    store.save_checkpoint(
        run_a,
        stage="s",
        schema_version=1,
        last_event_seq=1,
        state={"x": 1},
        db_path=isolated_db,
    )
    assert store.has_checkpoint(run_a, db_path=isolated_db)
    assert not store.has_checkpoint(run_b, db_path=isolated_db)
