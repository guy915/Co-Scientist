from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from evaluations import _run_driver, scaling_eval
from evaluations._identity import identity_digest, validate_identity
from evaluations.citation_usefulness_eval import run_deterministic


def test_identity_helpers_work_without_execution_imports() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
sys.modules["app"] = None
sys.modules["co_scientist"] = None
from evaluations._identity import (
    identity_digest, request_policy, validate_identity,
)
fields = {"version": 1, "dataset": {"name": "ordered", "items": []}}
sealed = {**fields, "digest": identity_digest(fields)}
assert validate_identity(sealed) is sealed
assert request_policy()
assert "evaluations._run_driver" not in sys.modules
assert "evaluations._usage_evidence" not in sys.modules
assert not any(name.startswith("app.") for name in sys.modules)
assert not any(name.startswith("co_scientist.") for name in sys.modules)
""",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_digest_preserves_order_independence_and_rejects_nonfinite_values() -> (
    None
):
    items = [1, 2]
    fields = {"version": 1, "dataset": {"name": "\u03b2", "items": items}}
    reordered = {"dataset": {"items": [1, 2], "name": "\u03b2"}, "version": 1}
    assert identity_digest(fields) == identity_digest(reordered)
    sealed = {**fields, "digest": identity_digest(fields)}
    assert validate_identity(sealed) is sealed
    items.append(3)
    with pytest.raises(ValueError, match="does not match its contents"):
        validate_identity(sealed)
    with pytest.raises(ValueError, match="JSON compliant"):
        identity_digest({"version": 1, "value": float("nan")})


def test_persisted_arm_freezes_inputs_and_model_policy(tmp_path: Path) -> None:
    from app.store import runs

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
    records = [runs.get_run(run_id, db_path=db) for run_id in ids]
    identities = [run.config["evaluation_identity"] for run in records]
    assert identities[0] == identities[1]
    assert identities[0]["digest"] != identities[2]["digest"]
    assert identities[0]["cache_policy"] == "disabled"
    assert identities[0]["backend"] == "offline"
    assert identities[0]["configured_models"]["worker"]
    assert identities[0]["request_policy_sha256"]
    engine = (
        Path(__file__).resolve().parents[2] / "engine" / "src" / "co_scientist"
    )
    for name in (
        "llm/admission/free_policy.py",
        "llm/profile/__init__.py",
        "llm/request/thinking.py",
    ):
        assert (
            identities[0]["request_policy_files"][name]
            == hashlib.sha256((engine / name).read_bytes()).hexdigest()
        )
    assert "API_KEY" not in str(identities)


def test_model_and_fallback_changes_change_persisted_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    import co_scientist.llm.profile as routes
    from app.config import settings
    from app.store import runs as store

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
        identity: dict[str, Any] = store.get_run(run_id, db_path=db).config[
            "evaluation_identity"
        ]
        return identity

    original = capture()
    model = settings.model_name
    declared = routes.ROUTES[model]
    monkeypatch.setitem(routes.ROUTES, model, {**declared, "fallbacks": ()})
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


@pytest.mark.parametrize("fault", ["missing", "corrupt", "model", "config"])
def test_invalid_identity_stops_before_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    from app import task_worker
    from app.config import settings
    from app.store import runs as store

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
    from app import task_worker
    from app.config import settings
    from app.store import runs as store

    from evaluations._identity import identity_digest

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


def _record(
    tmp_path: Path,
    goal: str = "Public goal",
    *,
    tier: str = "express",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app.store import runs as store

    db = str(tmp_path / "groups.db")
    _run_driver.configure_environment(db, str(tmp_path / "cache"), live=False)
    overrides = overrides or {}
    run_id = _run_driver.persist_arm_run(
        goal,
        tier,
        overrides,
        _run_driver.ArmInvocation("comparison-test", "offline", db),
    )
    return {
        "goal": goal,
        "goal_id": "public",
        "tier": tier,
        "overrides": overrides,
        "evaluation_identity": store.get_run(
            run_id,
            db_path=db,
        ).config["evaluation_identity"],
        "metrics": {},
        "hypotheses": [],
    }


@pytest.mark.parametrize("fault", ["missing", "goal", "model"])
def test_comparison_cli_rejects_incompatible_scaling_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    from app.config import settings

    first = _record(tmp_path)
    if fault == "model":
        monkeypatch.setattr(settings, "model_name", "openrouter/other:free")
    second = _record(
        tmp_path, "Other goal" if fault == "goal" else "Public goal"
    )
    if fault == "missing":
        del second["evaluation_identity"]
    path = tmp_path / "comparison.json"
    path.write_text(json.dumps({"snapshots": [first, second]}))
    monkeypatch.setattr("sys.argv", ["scaling_eval", str(path)])
    with pytest.raises(ValueError, match="comparison"):
        scaling_eval.main()


@pytest.mark.parametrize("declared", [True, False])
def test_ablation_cli_allows_only_declared_config_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    declared: bool,
) -> None:
    baseline = _record(tmp_path)
    candidate = _record(tmp_path, overrides={"enable_web_search": False})
    for record, arm in ((baseline, "baseline"), (candidate, "no_web_search")):
        record.update(arm=arm, diversity=0.0, cost_usd=0.0, latency_seconds=0.0)
    if not declared:
        candidate["overrides"] = {}
    path = tmp_path / "ablations.json"
    path.write_text(json.dumps({"ablations": [baseline, candidate]}))
    monkeypatch.setattr("sys.argv", ["scaling_eval", str(path)])
    if declared:
        assert scaling_eval.main() == 0
    else:
        with pytest.raises(ValueError, match="undeclared"):
            scaling_eval.main()


def test_historical_tier_profiles_do_not_use_current_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.run_modes import RUN_TIER_DEFAULTS

    records = [_record(tmp_path, tier=tier) for tier in ("express", "standard")]
    monkeypatch.setitem(RUN_TIER_DEFAULTS["express"], "max_llm_calls", 999999)
    path = tmp_path / "historical.json"
    path.write_text(json.dumps({"snapshots": records}))
    monkeypatch.setattr("sys.argv", ["scaling_eval", str(path)])
    assert scaling_eval.main() == 0


def test_ablation_cli_rejects_unbalanced_replicates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _record(tmp_path)
    candidate = _record(tmp_path, overrides={"enable_web_search": False})
    for record, arm in ((baseline, "baseline"), (candidate, "no_web_search")):
        record.update(arm=arm, diversity=0.0, cost_usd=0.0, latency_seconds=0.0)
    path = tmp_path / "unbalanced.json"
    path.write_text(json.dumps({"ablations": [baseline, candidate, candidate]}))
    monkeypatch.setattr("sys.argv", ["scaling_eval", str(path)])
    with pytest.raises(ValueError, match="comparison"):
        scaling_eval.main()


def test_ablation_cli_rejects_one_goal_counted_under_two_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = []
    for label in ("one", "two"):
        for arm, overrides in (
            ("baseline", {}),
            ("no_web", {"enable_web_search": False}),
        ):
            record = _record(tmp_path, overrides=overrides)
            record.update(
                goal_id=label,
                arm=arm,
                diversity=0.0,
                cost_usd=0.0,
                latency_seconds=0.0,
            )
            records.append(record)
    path = tmp_path / "repeated-goal.json"
    path.write_text(json.dumps({"ablations": records}))
    monkeypatch.setattr("sys.argv", ["scaling_eval", str(path)])
    with pytest.raises(ValueError, match="different labels"):
        scaling_eval.main()


def test_ablation_cli_rejects_a_baseline_relabeled_as_an_intervention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline, candidate = _record(tmp_path), _record(tmp_path)
    for record, arm in ((baseline, "baseline"), (candidate, "no_web_search")):
        record.update(arm=arm, diversity=0.0, cost_usd=0.0, latency_seconds=0.0)
    candidate["overrides"] = {"enable_web_search": False}
    path = tmp_path / "unapplied.json"
    path.write_text(json.dumps({"ablations": [baseline, candidate]}))
    monkeypatch.setattr("sys.argv", ["scaling_eval", str(path)])
    with pytest.raises(ValueError, match="comparison"):
        scaling_eval.main()


@pytest.mark.parametrize("same_intervention", [True, False])
def test_ablation_cli_matches_interventions_across_goals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, same_intervention: bool
) -> None:
    records = []
    for index, goal in enumerate(("Public goal one", "Public goal two")):
        intervention = {"enable_web_search": False}
        if index and not same_intervention:
            intervention = {"enable_meta_review": False}
        for arm, overrides in (("baseline", {}), ("no_feature", intervention)):
            record = _record(tmp_path, goal, overrides=overrides)
            record.update(
                goal_id=str(index),
                arm=arm,
                diversity=0.0,
                cost_usd=0.0,
                latency_seconds=0.0,
            )
            records.append(record)
    path = tmp_path / "interventions.json"
    path.write_text(json.dumps({"ablations": records}))
    monkeypatch.setattr("sys.argv", ["scaling_eval", str(path)])
    if same_intervention:
        assert scaling_eval.main() == 0
    else:
        with pytest.raises(ValueError, match="intervention"):
            scaling_eval.main()


def _compare(
    tmp_path: Path, left: dict[str, Any], right: dict[str, Any]
) -> subprocess.CompletedProcess[str]:
    paths = [tmp_path / "baseline.json", tmp_path / "candidate.json"]
    for path, report in zip(paths, (left, right), strict=True):
        path.write_text(json.dumps(report))
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "evaluations.panel_comparison",
            *map(str, paths),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_matched_panel_reports_are_comparable(tmp_path: Path) -> None:
    report = run_deterministic({"name": "frozen", "items": []})
    result = _compare(tmp_path, report, report)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "matched_declared_inputs"


@pytest.mark.parametrize(
    "change", ["dataset", "missing", "mode", "kind", "incomplete"]
)
def test_changed_panel_controls_are_rejected(
    tmp_path: Path, change: str
) -> None:
    report = run_deterministic({"name": "frozen", "items": []})
    candidate = copy.deepcopy(report)
    if change == "dataset":
        candidate = run_deterministic({"name": "different", "items": []})
    elif change == "missing":
        candidate.pop("evaluation_identity")
    elif change == "mode":
        candidate["execution_mode"] = "live_requested"
    else:
        _reseal_invalid_pair(report, candidate, change)
    result = _compare(tmp_path, report, candidate)
    assert result.returncode != 0
    assert "ValueError" in result.stderr


def _reseal_invalid_pair(
    report: dict[str, Any], candidate: dict[str, Any], change: str
) -> None:
    from evaluations._identity import identity_digest

    for artifact in (report, candidate):
        identity = artifact["evaluation_identity"]
        identity.pop("digest")
        if change == "incomplete":
            identity.pop("dataset")
        else:
            identity["kind"] = "arm"
        identity["digest"] = identity_digest(identity)
