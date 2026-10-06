from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from evaluations import _artifacts, _run_driver, scaling_eval
from evaluations._identity import identity_digest, validate_identity
from evaluations.citation_usefulness_eval import run_deterministic

_ROOT = Path(__file__).resolve().parents[2]


def _persist(
    tmp_path: Path,
    goal: str = "Public goal",
    tier: str = "express",
    overrides: dict[str, Any] | None = None,
) -> tuple[str, str]:
    db = str(tmp_path / "arms.db")
    _run_driver.configure_environment(db, str(tmp_path / "cache"), live=False)
    invocation = _run_driver.ArmInvocation("comparison-test", "offline", db)
    run_id = _run_driver.persist_arm_run(goal, tier, overrides or {}, invocation)
    return run_id, db


def _identity(run_id: str, db: str) -> dict[str, Any]:
    from app.store import runs

    identity: dict[str, Any] = runs.get_run(run_id, db_path=db).config["evaluation_identity"]
    return identity


def test_identity_helpers_work_without_execution_imports() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
sys.modules["app"] = None
sys.modules["co_scientist"] = None
from evaluations._identity import identity_digest, validate_identity
fields = {"version": 1, "dataset": {"name": "ordered", "items": []}}
sealed = {**fields, "digest": identity_digest(fields)}
assert validate_identity(sealed) is sealed
assert "evaluations._run_driver" not in sys.modules
assert not any(name.startswith("co_scientist.") for name in sys.modules)
""",
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_digest_is_order_independent_and_detects_tampering() -> None:
    items = [1, 2]
    fields = {"version": 1, "dataset": {"name": "β", "items": items}}
    reordered = {"dataset": {"items": [1, 2], "name": "β"}, "version": 1}
    assert identity_digest(fields) == identity_digest(reordered)
    sealed = {**fields, "digest": identity_digest(fields)}
    assert validate_identity(sealed) is sealed
    items.append(3)
    with pytest.raises(ValueError, match="does not match its contents"):
        validate_identity(sealed)
    with pytest.raises(ValueError, match="JSON compliant"):
        identity_digest({"version": 1, "value": float("nan")})


def test_persisted_arm_freezes_inputs_and_model_policy(tmp_path: Path) -> None:
    identity = _identity(*_persist(tmp_path))
    assert _identity(*_persist(tmp_path)) == identity
    other = _identity(*_persist(tmp_path, "Other goal"))
    assert other["digest"] != identity["digest"]
    assert identity["cache_policy"] == "disabled"
    assert identity["backend"] == "offline"
    assert identity["configured_models"]["worker"]
    engine = _ROOT / "engine" / "src" / "co_scientist"
    assert identity["request_policy_files"]
    for name, digest in identity["request_policy_files"].items():
        source = (engine / name).read_bytes()
        assert digest == hashlib.sha256(source).hexdigest()
    assert "API_KEY" not in str(identity)


def test_model_and_fallback_changes_change_persisted_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import co_scientist.llm.profile as routes
    from app.config import settings

    monkeypatch.setattr(settings, "model_name", "openrouter/minimax/minimax-m3:free")
    original = _identity(*_persist(tmp_path))
    model = settings.model_name
    declared = routes.ROUTES[model]
    monkeypatch.setitem(routes.ROUTES, model, {**declared, "fallbacks": ()})
    rerouted = _identity(*_persist(tmp_path))
    assert original["routing"] != rerouted["routing"]
    assert original["digest"] != rerouted["digest"]
    monkeypatch.setattr(settings, "model_name", "openrouter/test/other:free")
    changed_model = _identity(*_persist(tmp_path))
    assert changed_model["digest"] != rerouted["digest"]
    assert changed_model["goal_sha256"] == original["goal_sha256"]


def test_identity_refuses_an_enabled_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = str(tmp_path / "arms.db")
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from app import task_worker
    from app.config import settings
    from app.store import runs

    run_id, db = _persist(tmp_path)
    config = runs.get_run(run_id, db_path=db).config
    if fault == "missing":
        del config["evaluation_identity"]
    elif fault == "corrupt":
        config["evaluation_identity"]["goal_sha256"] = "altered"
    elif fault == "config":
        config["max_llm_calls"] += 1
    else:
        monkeypatch.setattr(settings, "model_name", "openrouter/changed:free")
    runs.set_run_config(run_id, config, db_path=db)

    async def must_not_run(*args: Any, **kwargs: Any) -> None:
        pytest.fail("worker started with an invalid comparison identity")

    monkeypatch.setattr(task_worker, "run_run_worker_pool", must_not_run)
    with pytest.raises(ValueError, match="comparison"):
        _run_driver.drive_arm_run(run_id, db)


@pytest.mark.parametrize("fault", ["model", "config", "identity"])
def test_worker_drift_cannot_produce_an_arm_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from app import task_worker
    from app.config import settings
    from app.store import runs

    db = str(tmp_path / "arms.db")
    _run_driver.configure_environment(db, str(tmp_path / "cache"), live=False)

    async def changed_worker(run_id: str, *args: Any, **kwargs: Any) -> None:
        if fault == "model":
            monkeypatch.setattr(settings, "model_name", "openrouter/changed:free")
            return
        config = runs.get_run(run_id, db_path=db).config
        if fault == "config":
            config["max_llm_calls"] += 1
        else:
            identity = config["evaluation_identity"]
            identity["claim_assessor"] = "altered"
            del identity["digest"]
            identity["digest"] = identity_digest(identity)
        runs.set_run_config(run_id, config, db_path=db)

    monkeypatch.setattr(task_worker, "run_run_worker_pool", changed_worker)
    with pytest.raises(ValueError, match="comparison"):
        _run_driver.run_arm(
            "Public goal",
            "express",
            {},
            _run_driver.ArmInvocation("comparison-test", "offline", db),
        )


def _record(tmp_path: Path, goal: str = "Public goal", **extra: Any) -> Any:
    tier = extra.pop("tier", "express")
    overrides = extra.get("overrides", {})
    run_id, db = _persist(tmp_path, goal, tier, overrides)
    return {
        "goal": goal,
        "goal_id": "public",
        "tier": tier,
        "overrides": overrides,
        "evaluation_identity": _identity(run_id, db),
        "metrics": {},
        "hypotheses": [],
        "diversity": 0.0,
        "cost_usd": 0.0,
        "latency_seconds": 0.0,
        **extra,
    }


def _run_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, records: Any) -> int:
    path = tmp_path / "records.json"
    path.write_text(json.dumps({key: records}))
    monkeypatch.setattr("sys.argv", ["scaling_eval", str(path)])
    return scaling_eval.main()


@pytest.mark.parametrize("fault", ["none", "missing", "goal", "model"])
def test_scaling_comparison_requires_matching_identities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from app.config import settings

    first = _record(tmp_path)
    if fault == "model":
        monkeypatch.setattr(settings, "model_name", "openrouter/other:free")
    goal = "Other goal" if fault == "goal" else "Public goal"
    second = _record(tmp_path, goal)
    if fault == "missing":
        del second["evaluation_identity"]
    records = [first, second]
    if fault == "none":
        assert _run_cli(tmp_path, monkeypatch, "snapshots", records) == 0
    else:
        with pytest.raises(ValueError, match="comparison"):
            _run_cli(tmp_path, monkeypatch, "snapshots", records)


def test_historical_tier_profiles_do_not_use_current_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.run_modes import RUN_TIER_DEFAULTS

    records = [_record(tmp_path, tier=tier) for tier in ("express", "standard")]
    monkeypatch.setitem(RUN_TIER_DEFAULTS["express"], "max_llm_calls", 999999)
    assert _run_cli(tmp_path, monkeypatch, "snapshots", records) == 0


_GOALS = {"one": "Public goal one", "two": "Public goal two"}
_NO_WEB = {"enable_web_search": False}
_NO_META = {"enable_meta_review": False}
_PAIR = [("public", "baseline", {}), ("public", "no_web", _NO_WEB)]
_ONE = [("one", "baseline", {}), ("one", "no_feature", _NO_WEB)]
_ARMS: dict[str, list[tuple[str, str, dict[str, Any]]]] = {
    "declared": _PAIR,
    "undeclared": _PAIR,
    "unapplied": [_PAIR[0], ("public", "no_web", {})],
    "unbalanced": [*_PAIR, _PAIR[1]],
    "relabeled_goal": [
        *_PAIR,
        ("alias", "baseline", {}),
        ("alias", "no_web", _NO_WEB),
    ],
    "same_intervention": [
        *_ONE,
        ("two", "baseline", {}),
        ("two", "no_feature", _NO_WEB),
    ],
    "different_intervention": [
        *_ONE,
        ("two", "baseline", {}),
        ("two", "no_feature", _NO_META),
    ],
}
# Overrides a record claims although its identity was sealed without (or
# with) them.
_CLAIMED = {"undeclared": {}, "unapplied": _NO_WEB}


@pytest.mark.parametrize(
    ("scenario", "error"),
    [
        ("declared", None),
        ("same_intervention", None),
        ("unbalanced", "comparison"),
        ("relabeled_goal", "different labels"),
        ("different_intervention", "intervention"),
        ("undeclared", "undeclared"),
        ("unapplied", "comparison"),
    ],
)
def test_ablation_comparison_accepts_only_declared_balanced_arms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    error: str | None,
) -> None:
    records = [
        _record(
            tmp_path,
            _GOALS.get(goal_id, "Public goal"),
            goal_id=goal_id,
            arm=arm,
            overrides=overrides,
        )
        for goal_id, arm, overrides in _ARMS[scenario]
    ]
    if scenario in _CLAIMED:
        records[1]["overrides"] = _CLAIMED[scenario]
    if error is None:
        assert _run_cli(tmp_path, monkeypatch, "ablations", records) == 0
    else:
        with pytest.raises(ValueError, match=error):
            _run_cli(tmp_path, monkeypatch, "ablations", records)


def _reseal(artifact: dict[str, Any], **changes: Any) -> None:
    identity = artifact["evaluation_identity"]
    identity.pop("digest")
    for key, value in changes.items():
        if value is None:
            identity.pop(key)
        else:
            identity[key] = value
    identity["digest"] = identity_digest(identity)


def _changed_panel(report: dict[str, Any], change: str) -> dict[str, Any]:
    candidate = copy.deepcopy(report)
    if change == "dataset":
        return run_deterministic({"name": "different", "items": []})
    if change == "missing":
        candidate.pop("evaluation_identity")
    if change == "mode":
        candidate["execution_mode"] = "live_requested"
    if change in ("kind", "incomplete"):
        changes: dict[str, Any] = {"kind": "arm"} if change == "kind" else {"dataset": None}
        _reseal(report, **changes)
        _reseal(candidate, **changes)
    return candidate


@pytest.mark.parametrize("change", ["none", "dataset", "missing", "mode", "kind", "incomplete"])
def test_panel_comparison_requires_matched_declared_inputs(tmp_path: Path, change: str) -> None:
    report = run_deterministic({"name": "frozen", "items": []})
    candidate = _changed_panel(report, change)
    paths = [tmp_path / "baseline.json", tmp_path / "candidate.json"]
    for path, artifact in zip(paths, (report, candidate), strict=True):
        path.write_text(json.dumps(artifact))
    result = subprocess.run(
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
    if change == "none":
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["status"] == "matched_declared_inputs"
    else:
        assert result.returncode != 0
        assert "ValueError" in result.stderr


def test_provenance_records_source_and_prompts_and_passes_inputs_through() -> None:
    provenance = _artifacts.build_provenance(
        model="offline/test-model", seed="42", cost={"total_usd": 0.01}
    )

    assert provenance["source"]["git_commit"] != "unknown"
    assert provenance["prompts"]["file_count"] > 0
    assert provenance["prompts"]["digest"] is not None
    assert provenance["model"] == "offline/test-model"
    assert provenance["seed"] == "42"
    assert provenance["cost"] == {"total_usd": 0.01}


@pytest.fixture
def scratch_results_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    # The writer uses relative_to, so artifacts must stay under the repo root.
    scratch = _artifacts._RESULTS_DIR / "_pytest_scratch_artifacts"
    monkeypatch.setattr(_artifacts, "_RESULTS_DIR", scratch)
    try:
        yield scratch
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def test_dated_artifact_stamps_provenance_and_defaults_unknowns_to_none(
    scratch_results_dir: Path,
) -> None:
    out = _artifacts.write_dated_artifact(
        {"ok": True}, "unit-test-artifact", model="m", seed=1, cost=0.0
    )
    written = json.loads((_artifacts._ROOT / out).read_text())
    assert written["ok"] is True
    assert (written["provenance"]["model"], written["provenance"]["seed"]) == (
        "m",
        1,
    )

    out = _artifacts.write_dated_artifact({"n": 1}, "unit-test-defaults")
    provenance = json.loads((_artifacts._ROOT / out).read_text())["provenance"]
    assert [provenance[key] for key in ("model", "seed", "cost")] == [None] * 3
