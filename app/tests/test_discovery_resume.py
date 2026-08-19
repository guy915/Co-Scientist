"""A discovery run has to survive the process that was running it.

Its progress is entirely durable -- every variant, every metric, every
task row -- and yet it was the one kind of run a restart destroyed,
because resumability was decided by a single test (is there a
checkpoint?) that a discovery run can never pass. It has no Supervisor
and no graph state, so it writes none. The result was inverted: the run
whose state survived intact got failed, while a hypothesis run whose
engine state was gone got resumed.

What makes it resumable instead is the queue. Generation keys are
deterministic (``variant:propose:{gen}:{i}`` and friends), so re-entering
duplicates nothing.
"""

from __future__ import annotations

from typing import Any

import pytest

from app import store
from app.config import settings
from app.engine_tasks_variants import VARIANT_PROPOSE_TASK


def _discovery_config() -> dict[str, Any]:
    return {
        "discovery": {
            "objective": {"metric": "score", "direction": "maximize"},
            "stages": [{"name": "run", "argv": ["python", "main.py"]}],
            "seed_source": {"main.py": "print(1)"},
        }
    }


def _make_run(
    isolated_db: str, config: dict[str, Any], client_id: str = "c1"
) -> str:
    run = store.create_run(
        "evolve it",
        "default",
        "engine",
        config,
        store.RunCreateOptions(client_id=client_id, db_path=isolated_db),
    )
    store.update_run_status(
        run.id, store.RunStatus.RUNNING, db_path=isolated_db
    )
    return run.id


def _enqueue_variant_task(run_id: str, isolated_db: str, key: str) -> Any:
    return store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=VARIANT_PROPOSE_TASK,
            inputs={"parent_variant_id": None, "seed_index": 0},
            idempotency_key=key,
        ),
        db_path=isolated_db,
    )


def _interrupted_discovery_run(isolated_db: str, client_id: str = "c1") -> str:
    """A discovery run as a restart leaves it: work queued, no checkpoint."""
    run_id = _make_run(isolated_db, _discovery_config(), client_id)
    _enqueue_variant_task(run_id, isolated_db, "variant:propose:0:0")
    return run_id


class TestReconciliation:
    """What the startup sweep does with a run it finds still active."""

    def test_a_discovery_run_with_queued_work_is_resumable(
        self, isolated_db: str
    ) -> None:
        run_id = _interrupted_discovery_run(isolated_db)

        reconciled = store.reconcile_interrupted_runs(db_path=isolated_db)

        assert reconciled["resumable"] == [run_id]
        assert reconciled["failed"] == []
        row = store.get_run(run_id, db_path=isolated_db)
        assert row is not None
        assert row.status != store.RunStatus.FAILED.value

    def test_the_resumable_event_names_the_queue_not_a_checkpoint(
        self, isolated_db: str
    ) -> None:
        # The run has no checkpoint, so saying it has one would be the
        # stream describing a durable thing that does not exist.
        run_id = _interrupted_discovery_run(isolated_db)

        store.reconcile_interrupted_runs(db_path=isolated_db)

        details = [
            event["payload"].get("detail")
            for event in store.list_events(run_id, db_path=isolated_db)
            if event["payload"].get("status") == "resumable"
        ]
        assert details == ["durable task queue"]

    def test_a_discovery_run_with_nothing_claimable_still_fails(
        self, isolated_db: str
    ) -> None:
        """Being a discovery run is not on its own a reason to resume.

        With no unfinished task there is nothing for a worker to take,
        so resuming would announce a resume on every restart and then
        sit silent -- the exact wedge the resume log line exists to
        expose. This run is stuck, and saying so is the honest outcome.
        """
        run_id = _make_run(isolated_db, _discovery_config())

        reconciled = store.reconcile_interrupted_runs(db_path=isolated_db)

        assert reconciled["failed"] == [run_id]

    def test_a_hypothesis_run_without_a_checkpoint_still_fails(
        self, isolated_db: str
    ) -> None:
        # Pins that the new path is reached by discovery runs only. A
        # hypothesis run's state lives in the checkpoint; queued tasks
        # are not a substitute for it.
        run_id = _make_run(isolated_db, {})
        _enqueue_variant_task(run_id, isolated_db, "variant:propose:0:0")

        reconciled = store.reconcile_interrupted_runs(db_path=isolated_db)

        assert reconciled["failed"] == [run_id]


class TestThePredicate:
    """``has_resumable_discovery_work`` -- one answer, four callers."""

    def test_a_leased_task_counts_as_work(self, isolated_db: str) -> None:
        # This is the shape a restart actually leaves: the task was
        # leased to a worker that no longer exists. Its lease expires
        # and the next cohort reclaims it.
        run_id = _interrupted_discovery_run(isolated_db)
        store.claim_task("worker-1", db_path=isolated_db)

        assert store.has_resumable_discovery_work(run_id, db_path=isolated_db)

    def test_a_succeeded_queue_is_not_work(self, isolated_db: str) -> None:
        run_id = _interrupted_discovery_run(isolated_db)
        claimed = store.claim_task("worker-1", db_path=isolated_db)
        assert claimed is not None
        store.complete_task(claimed.id, "worker-1", {}, db_path=isolated_db)

        assert not store.has_resumable_discovery_work(
            run_id, db_path=isolated_db
        )

    def test_an_unknown_run_is_not_work(self, isolated_db: str) -> None:
        assert not store.has_resumable_discovery_work(
            "no-such-run", db_path=isolated_db
        )

    def test_a_malformed_config_is_not_a_discovery_run(
        self, isolated_db: str
    ) -> None:
        run_id = _make_run(isolated_db, {"discovery": "not-a-block"})
        _enqueue_variant_task(run_id, isolated_db, "variant:propose:0:0")

        assert not store.has_resumable_discovery_work(
            run_id, db_path=isolated_db
        )


class TestResuming:
    """What the resume itself does to a run a restart interrupted."""

    def test_it_lands_on_the_work_already_queued(
        self, isolated_db: str
    ) -> None:
        from app import task_worker

        run_id = _interrupted_discovery_run(isolated_db)
        before = len(store.list_tasks(run_id, db_path=isolated_db))

        landed = task_worker.enqueue_run_workflow(
            run_id, resume=True, db_path=isolated_db
        )

        # The queue already held the work; a resume that invents a
        # second entry point is a resume that lands on nothing.
        assert landed.task_type == VARIANT_PROPOSE_TASK
        assert landed.status == "queued"
        assert len(store.list_tasks(run_id, db_path=isolated_db)) == before

    def test_it_keeps_the_events_describing_the_variants(
        self, isolated_db: str
    ) -> None:
        """The data-loss case, and the reason discovery is a *true* resume.

        Read as a legacy checkpoint, a discovery resume clears derived
        data -- which deletes ``run_events``, and with them every
        ``discovery`` event narrating a variant that is still sitting in
        ``code_variants``. The run would come back with its search
        intact and no account of it.
        """
        run_id = _interrupted_discovery_run(isolated_db)
        store.append_event(
            run_id,
            "discovery",
            {"variant": "v1", "fitness": 0.5},
            db_path=isolated_db,
        )

        from app import runs_lifecycle

        store.reconcile_interrupted_runs(db_path=isolated_db)
        true_resume = runs_lifecycle._prepare_resume_state(run_id)

        kinds = [
            event["type"]
            for event in store.list_events(run_id, db_path=isolated_db)
        ]
        assert "discovery" in kinds
        assert true_resume is True

    def test_the_endpoint_picks_up_a_run_an_earlier_restart_failed(
        self, isolated_db: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Drives the recovery path the docstrings advertise, end to end.

        A run the old sweep failed is not a lost run: failing one never
        touched its task rows, so the work is still queued with its
        retry budget intact and a failed run passes both of the
        endpoint's 409 guards. This asserts the whole seam, including
        that the transition out of a terminal status clears the stale
        "interrupted by a server restart" error and completion time it
        would otherwise carry while running.
        """
        monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
        from tests._client import DEFAULT_TEST_CLIENT_ID, make_client

        run_id = _interrupted_discovery_run(
            isolated_db, client_id=DEFAULT_TEST_CLIENT_ID
        )
        store.update_run_status(
            run_id,
            store.RunStatus.FAILED,
            error="Run interrupted by a server restart.",
            db_path=isolated_db,
        )

        client = make_client()
        resumed = client.post(f"/api/runs/{run_id}/resume")

        assert resumed.status_code == 200
        row = store.get_run(run_id, db_path=isolated_db)
        assert row is not None
        assert row.status == store.RunStatus.QUEUED.value
        assert row.error is None
        assert row.completed_at is None
        # The work it resumes onto is the work that was always there.
        assert [
            task.status
            for task in store.list_tasks(run_id, db_path=isolated_db)
        ] == ["queued"]

    def test_a_run_an_earlier_restart_failed_is_seen_as_resumable(
        self, isolated_db: str
    ) -> None:
        """The recovery path for runs the old behaviour already bricked.

        Failing an interrupted run never touched its task rows, so their
        retry budgets are intact and the work is still claimable. A
        failed run passes both of the endpoint's 409 guards, so the only
        thing that stood between those runs and a resume was the
        checkpoint test.
        """
        run_id = _interrupted_discovery_run(isolated_db)
        store.update_run_status(
            run_id,
            store.RunStatus.FAILED,
            error="Run interrupted by a server restart.",
            db_path=isolated_db,
        )

        from app import runs_lifecycle

        assert [
            task.status
            for task in store.list_tasks(run_id, db_path=isolated_db)
        ] == ["queued"]
        assert runs_lifecycle._is_resumable(run_id) is True
