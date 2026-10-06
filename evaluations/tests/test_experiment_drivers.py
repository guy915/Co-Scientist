from __future__ import annotations

import pathlib
import tempfile
from typing import Any

import pytest

from evaluations import _run_driver
from evaluations.ablation_driver import PUBLISHED_BASELINES, run_ablation_sweep
from evaluations.scaling_budget_driver import run_budget_curve

_GOALS = (
    (
        "test-goal-1",
        "Propose a mechanism for acquired resistance to EGFR tyrosine "
        "kinase inhibitors in EGFR-mutant lung adenocarcinoma.",
    ),
)
_ARMS: dict[str, dict[str, Any]] = {
    "baseline": {},
    "no_web_search": {"enable_web_search": False},
    "no_meta_review": {"enable_meta_review": False},
    "debate_only_strategy": {"generation_strategy": "no_lit"},
}


def _drive_one_arm(
    overrides: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    # Read the persisted checkpoint to prove toggles reached workflow state, not
    # only run configuration.
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ablation-arm-"))
    db_path = str(tmp / "arm.db")
    _run_driver.configure_environment(db_path, live=False)
    arm = _run_driver.run_arm(
        _GOALS[0][1],
        "express",
        overrides,
        _run_driver.ArmInvocation(
            client_id="ablation-test",
            backend="offline",
            db_path=db_path,
        ),
    )
    return arm, db_path


def _persisted_state(run_id: str, db_path: str) -> dict[str, Any]:
    from app.store import checkpoints as store

    checkpoint = store.get_latest_checkpoint(run_id, db_path=db_path)
    assert checkpoint is not None, "run left no checkpoint"
    state: dict[str, Any] = checkpoint["state"]["state"]
    return state


def test_offline_ablation_sweep_pairs_every_goal_across_arms() -> None:
    report = run_ablation_sweep(_GOALS, "express", live=False, arms=_ARMS)

    assert report["mode"] == "offline"
    assert report["arms_run"] == sorted(_ARMS)
    assert len(report["driven"]) == len(_GOALS) * len(_ARMS)
    for arm in report["driven"]:
        assert arm["completed"], arm
        assert arm["used_real_backend"] is False

    summary = report["summary"]
    assert summary["paired_goal_count"] == 1
    assert set(summary["arms"]) == set(_ARMS)
    by_run = {arm["run_id"]: arm for arm in report["driven"]}
    for record in report["records"]:
        assert record["evaluation_identity"] == by_run[record["run_id"]]["evaluation_identity"]
        assert record["cost_usd"] == 0.0, "offline calls must cost nothing"
        assert isinstance(record["latency_seconds"], float)
        assert isinstance(record["diversity"], float)
    assert "no_meta_review" not in report["unreachable_arms"]
    assert "no_evolution" in report["unreachable_arms"]
    # Reference baselines are report data and never feed computed summaries.
    assert report["published_baselines"] == PUBLISHED_BASELINES
    assert "published_baselines" not in summary


@pytest.mark.parametrize(
    ("overrides", "key", "value"),
    [
        ({"enable_meta_review": False}, "enable_meta_review", False),
        ({"generation_strategy": "no_lit"}, "generation_strategy", "no_lit"),
    ],
)
def test_ablation_toggles_reach_persisted_workflow_state(
    overrides: dict[str, Any], key: str, value: Any
) -> None:
    arm, db_path = _drive_one_arm(overrides)
    assert arm["completed"], arm
    assert _persisted_state(arm["run_id"], db_path)[key] == value


def test_offline_budget_curve_orders_tiers_by_compute() -> None:
    report = run_budget_curve(
        "Explain a plausible mechanism of antibiotic tolerance in biofilm-embedded bacteria.",
        ["express", "standard"],
        live=False,
    )

    assert report["mode"] == "offline"
    assert report["offline_disclaimer"]
    for arm in report["arms"]:
        assert arm["completed"], arm
        assert arm["used_real_backend"] is False
    low, high = report["curve"]
    assert low["hypothesis_count"] <= high["hypothesis_count"]
    assert low["compute"]["llm_calls"] <= high["compute"]["llm_calls"]
    for point in (low, high):
        assert point["cost_usd"] == 0.0, "offline calls must cost nothing"
        assert point["latency_seconds"] > 0

    snapshot = report["snapshots"][0]
    assert snapshot["goal_id"] == report["goal_id"]
    identity = snapshot["evaluation_identity"]
    assert identity == report["arms"][0]["evaluation_identity"]
    for hypothesis in snapshot["hypotheses"]:
        assert isinstance(hypothesis["assessed_claims"], int)
        assert isinstance(hypothesis["verified_claims"], int)
        assert "elo_rating" in hypothesis

    curve = snapshot["temporal_curve"]
    assert 0 < len(curve) <= 10
    assert sum(b["n_hypotheses"] for b in curve) == len(snapshot["hypotheses"])
    # Express still runs one evolution round, so cycle and lineage must vary
    # end to end (engine stamp, drain, store, eval) for the curve to order
    # anything real.
    assert len({h["creation_iteration"] for h in snapshot["hypotheses"]}) >= 2
    assert len({h["generation"] for h in snapshot["hypotheses"]}) >= 2
    assert all(b["best_elo"] is not None for b in curve)
