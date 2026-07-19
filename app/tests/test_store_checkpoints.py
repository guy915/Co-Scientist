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


def _count(db: str) -> int:
    """Return the total number of checkpoint rows across all runs."""
    with store.connect(db) as conn:
        return int(
            conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
        )


def test_saving_prunes_the_checkpoints_it_supersedes(isolated_db: str) -> None:
    """Only the newest checkpoint survives, because only it is readable.

    Regression: every boundary crossed used to leave a full WorkflowState
    snapshot behind forever. In production that grew the checkpoints table to
    380 MB -- 97% of the database -- and filled the volume until every write
    failed with "database or disk is full".
    """
    run_id = _run(isolated_db)
    for i in range(5):
        store.save_checkpoint(
            run_id,
            stage=f"stage_{i}",
            schema_version=1,
            last_event_seq=i,
            state={"round": i},
            db_path=isolated_db,
        )

    assert _count(isolated_db) == 1
    latest = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None
    # Pruning must not disturb the seq counter: it is assigned as MAX(seq) + 1
    # and the bootstrap path asserts on it.
    assert latest["seq"] == 5
    assert latest["stage"] == "stage_4"
    assert latest["state"] == {"round": 4}
    assert store.has_checkpoint(run_id, db_path=isolated_db)


def test_pruning_is_per_run(isolated_db: str) -> None:
    """One run's checkpoints are never pruned by another run's progress."""
    first, second = _run(isolated_db), _run(isolated_db)
    for run_id in (first, second):
        for i in range(3):
            store.save_checkpoint(
                run_id,
                stage=f"s{i}",
                schema_version=1,
                last_event_seq=i,
                state={"run": run_id, "round": i},
                db_path=isolated_db,
            )

    assert _count(isolated_db) == 2
    for run_id in (first, second):
        latest = store.get_latest_checkpoint(run_id, db_path=isolated_db)
        assert latest is not None
        assert latest["state"]["run"] == run_id
        assert latest["seq"] == 3


def test_prune_superseded_reclaims_pre_existing_history(
    isolated_db: str,
) -> None:
    """The startup sweep applies the rule to a database written without it.

    Simulates the production database: rows inserted directly, bypassing the
    pruning write path, exactly as the old code left them.
    """
    run_id = _run(isolated_db)
    with store.connect(isolated_db) as conn:
        for i in range(1, 21):
            conn.execute(
                "INSERT INTO checkpoints (run_id, seq, stage, schema_version, "
                "last_event_seq, state_json, created_at) "
                "VALUES (?, ?, ?, 1, ?, ?, 0.0)",
                (run_id, i, f"stage_{i}", i, f'{{"round": {i}}}'),
            )
    assert _count(isolated_db) == 20

    deleted = store.prune_superseded_checkpoints(db_path=isolated_db)

    assert deleted == 19
    assert _count(isolated_db) == 1
    # The run is still resumable, from precisely the boundary it reached.
    latest = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None
    assert latest["seq"] == 20
    assert latest["state"] == {"round": 20}


def test_prune_superseded_is_idempotent(isolated_db: str) -> None:
    """Safe to run on every startup: a second sweep finds nothing to do."""
    run_id = _run(isolated_db)
    store.save_checkpoint(
        run_id,
        stage="only",
        schema_version=1,
        last_event_seq=1,
        state={},
        db_path=isolated_db,
    )

    assert store.prune_superseded_checkpoints(db_path=isolated_db) == 0
    assert store.prune_superseded_checkpoints(db_path=isolated_db) == 0
    assert store.has_checkpoint(run_id, db_path=isolated_db)
