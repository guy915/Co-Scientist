"""Comparison CLI rejects incompatible declared research inputs."""

import json
from pathlib import Path
from typing import Any

import pytest

from evaluations import _run_driver, scaling_eval


def _record(
    tmp_path: Path,
    goal: str = "Public goal",
    *,
    tier: str = "express",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app import store

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
