from __future__ import annotations

import asyncio
from typing import Any

import pytest
from co_scientist.llm.request import backend
from co_scientist.offline import llm as offline_llm

from app import task_worker
from app.store import events as store_events
from app.store import hypotheses, reports, runs
from app.store.models import RunStatus
from app.store.runs import RunCreateOptions

from ._llm_fake_backend import load_engine_fake


@pytest.fixture(autouse=True)
def _isolate_offline_router(monkeypatch: pytest.MonkeyPatch) -> None:
    # Offline backend registration is process-global; restore it and clear
    # idempotency state.
    monkeypatch.setattr(backend, "_installed", backend._installed)
    monkeypatch.setattr(offline_llm, "_installed", False)


def _install_recording_router(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    # Record escaped provider calls while answering offline so leaks cannot make
    # paid calls.
    escaped_calls: list[dict[str, Any]] = []

    async def _recording_backend(**kwargs: Any) -> Any:
        escaped_calls.append(kwargs)
        return await offline_llm.offline_acompletion(**kwargs)

    load_engine_fake().install_fake_backend(monkeypatch, _recording_backend)
    offline_llm.install_offline_router()
    return escaped_calls


def _persist_offline_run(isolated_db: str) -> tuple[Any, dict[str, Any]]:
    config: dict[str, Any] = {
        "tier": "express",
        "enable_literature_review": False,
    }
    run = runs.create_run(
        "Explain how protein X folds under crowding.",
        "express",
        "mock",
        config,
        RunCreateOptions(
            client_id="offline-e2e", llm_backend="offline", db_path=isolated_db
        ),
    )
    return run, config


def _drive_offline_engine(
    run: Any, config: dict[str, Any], isolated_db: str
) -> list[dict[str, Any]]:
    _ = config
    task_worker.enqueue_run_workflow(run.id, db_path=isolated_db)
    asyncio.run(
        task_worker.run_run_worker_pool(
            run.id,
            "offline-e2e-test",
            policy=task_worker.WorkerPolicy(db_path=isolated_db),
        )
    )
    return store_events.list_events(run.id, db_path=isolated_db)


def test_offline_engine_run_completes_without_a_real_call(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)
    escaped_calls = _install_recording_router(monkeypatch)
    run, config = _persist_offline_run(isolated_db)
    events = _drive_offline_engine(run, config, isolated_db)

    assert not escaped_calls, (
        "a call reached the wrapped backend instead of the offline "
        f"router: {escaped_calls[0].get('model')!r}"
    )

    types_emitted = [e["type"] for e in events]
    assert "report" in types_emitted
    final = runs.get_run(run.id, db_path=isolated_db)
    assert final is not None
    assert final.status == RunStatus.COMPLETED.value
    assert final.llm_backend == "offline"
    assert reports.get_latest_report(run.id, db_path=isolated_db) is not None

    hyps = hypotheses.list_hypotheses(run.id, db_path=isolated_db)
    assert hyps
