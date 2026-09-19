"""Durable evaluation arms reject changed control settings."""

from pathlib import Path
from typing import Any

import pytest

from evaluations import _run_driver


@pytest.mark.parametrize("fault", ["missing", "corrupt", "model", "config"])
def test_invalid_identity_stops_before_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    from app import store, task_worker
    from app.config import settings

    db = str(tmp_path / "drift.db")
    _run_driver.configure_environment(db, str(tmp_path / "cache"), live=False)
    run_id = _run_driver.persist_arm_run(
        "Public goal",
        "express",
        {},
        _run_driver.ArmInvocation("comparison-test", "offline", db),
    )
    config = store.get_run(run_id, db_path=db).config
    if fault == "missing":
        del config["evaluation_identity"]
    elif fault == "corrupt":
        config["evaluation_identity"]["goal_sha256"] = "altered"
    elif fault == "config":
        config["max_llm_calls"] += 1
    else:
        monkeypatch.setattr(settings, "model_name", "openrouter/changed:free")
    store.set_run_config(run_id, config, db_path=db)

    async def must_not_run(*args: Any, **kwargs: Any) -> None:
        pytest.fail("worker started with an invalid comparison identity")

    monkeypatch.setattr(task_worker, "run_run_worker_pool", must_not_run)
    with pytest.raises(ValueError, match="comparison"):
        _run_driver.drive_arm_run(run_id, db)


@pytest.mark.parametrize("fault", ["model", "config", "identity"])
def test_worker_drift_cannot_produce_an_arm_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    from app import store, task_worker
    from app.config import settings

    from evaluations._comparison_identity import identity_digest

    db = str(tmp_path / "post-drift.db")
    _run_driver.configure_environment(db, str(tmp_path / "cache"), live=False)

    async def changed_worker(run_id: str, *args: Any, **kwargs: Any) -> None:
        if fault == "model":
            monkeypatch.setattr(
                settings, "model_name", "openrouter/changed:free"
            )
            return
        config = store.get_run(run_id, db_path=db).config
        if fault == "config":
            config["max_llm_calls"] += 1
        else:
            identity = config["evaluation_identity"]
            identity["claim_assessor"] = "altered"
            del identity["digest"]
            identity["digest"] = identity_digest(identity)
        store.set_run_config(run_id, config, db_path=db)

    monkeypatch.setattr(task_worker, "run_run_worker_pool", changed_worker)
    with pytest.raises(ValueError, match="comparison"):
        _run_driver.run_arm(
            "Public goal",
            "express",
            {},
            _run_driver.ArmInvocation("comparison-test", "offline", db),
        )
