"""Controlled run inputs survive persistence and artifact collection."""

from pathlib import Path
from typing import Any

import pytest

from evaluations import _run_driver


def test_persisted_arm_freezes_inputs_and_model_policy(tmp_path: Path) -> None:
    from app import store

    db = str(tmp_path / "comparison.db")
    _run_driver.configure_environment(db, str(tmp_path / "cache"), live=False)
    invocation = _run_driver.ArmInvocation("comparison-test", "offline", db)
    ids = [
        _run_driver.persist_arm_run(goal, "express", {}, invocation)
        for goal in (
            "Public research goal",
            "Public research goal",
            "Other goal",
        )
    ]
    records = [store.get_run(run_id, db_path=db) for run_id in ids]
    identities = [run.config["evaluation_identity"] for run in records]
    assert identities[0] == identities[1]
    assert identities[0]["digest"] != identities[2]["digest"]
    assert identities[0]["cache_policy"] == "disabled"
    assert identities[0]["backend"] == "offline"
    assert identities[0]["configured_models"]["worker"]
    assert identities[0]["request_policy_sha256"]
    assert "API_KEY" not in str(identities)


def test_model_and_fallback_changes_change_persisted_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dataclasses

    from app import store
    from app.config import settings
    from co_scientist import llm_gateway_routing

    db = str(tmp_path / "model-policy.db")
    _run_driver.configure_environment(db, str(tmp_path / "cache"), live=False)
    invocation = _run_driver.ArmInvocation("comparison-test", "offline", db)

    monkeypatch.setattr(
        settings, "model_name", "openrouter/minimax/minimax-m3:free"
    )

    def capture() -> dict[str, Any]:
        run_id = _run_driver.persist_arm_run(
            "Public goal",
            "express",
            {},
            invocation,
        )
        return store.get_run(run_id, db_path=db).config["evaluation_identity"]

    original = capture()
    model = settings.model_name
    declared = llm_gateway_routing._GATEWAY_MODELS[model]
    monkeypatch.setitem(
        llm_gateway_routing._GATEWAY_MODELS,
        model,
        dataclasses.replace(declared, fallbacks=()),
    )
    rerouted = capture()
    assert original["routing"] != rerouted["routing"]
    assert original["digest"] != rerouted["digest"]
    monkeypatch.setattr(settings, "model_name", "openrouter/test/other:free")
    changed_model = capture()
    assert changed_model["digest"] != rerouted["digest"]
    assert changed_model["goal_sha256"] == original["goal_sha256"]


def test_identity_refuses_an_enabled_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = str(tmp_path / "cache.db")
    _run_driver.configure_environment(db, str(tmp_path / "cache"), live=False)
    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "1")
    with pytest.raises(ValueError, match="disabled response caches"):
        _run_driver.persist_arm_run(
            "Public goal",
            "express",
            {},
            _run_driver.ArmInvocation("comparison-test", "offline", db),
        )
