"""An intake redaction must scrub the stored goal, not just label it.

The bootstrap gate recorded ``decision="redact"`` and then prepared the
workflow from the same ``runs.research_goal`` column, so the original stayed
readable through ``GET /api/runs/{id}``, the run list, and every report built
from it. These drive the real durable bootstrap and read the row back.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app import engine_tasks, safety, store, task_worker
from app.safety import REDACTED_PLACEHOLDER

_STRICT_GOAL = "Assess select agent stockpile resilience across regions."


@pytest.fixture(autouse=True)
def _strict_intake(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the intake gate in strict mode, where dual-use content redacts."""
    monkeypatch.setattr(safety, "SAFETY_MODE", safety.SafetyMode.STRICT)


def _persist_run(db_path: str) -> Any:
    """Persist an offline-backed run whose goal trips the dual-use rule."""
    return store.create_run(
        _STRICT_GOAL,
        "express",
        "engine",
        {"tier": "express", "enable_literature_review": False},
        store.RunCreateOptions(
            client_id="intake-redaction",
            title=f"Study of {_STRICT_GOAL}",
            llm_backend="offline",
            db_path=db_path,
        ),
    )


async def test_intake_redaction_scrubs_the_persisted_goal(
    isolated_db: str,
) -> None:
    """The stored goal and title lose the matched span before the run starts."""
    run = _persist_run(isolated_db)
    assert safety.screen_intake(_STRICT_GOAL).decision == "redact"

    task_worker.enqueue_run_workflow(run.id, db_path=isolated_db)
    task = store.claim_task(
        "intake-redaction-worker", db_path=isolated_db, run_id=run.id
    )
    assert task is not None
    await engine_tasks.execute_bootstrap(task, db_path=isolated_db)

    stored = store.get_run(run.id, db_path=isolated_db)
    assert stored is not None
    assert "select agent" not in stored.research_goal.lower()
    assert REDACTED_PLACEHOLDER in stored.research_goal
    assert "select agent" not in (stored.title or "").lower()


def test_intake_redaction_survives_into_the_report(isolated_db: str) -> None:
    """A redacted goal never reappears in the published run artifacts."""
    run = _persist_run(isolated_db)
    task_worker.enqueue_run_workflow(run.id, db_path=isolated_db)
    asyncio.run(
        task_worker.run_run_worker_pool(
            run.id,
            "intake-redaction-e2e",
            policy=task_worker.WorkerPolicy(db_path=isolated_db),
        )
    )

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert "select agent" not in report["markdown_text"].lower()
    assert "select agent" not in repr(report["payload"]).lower()
