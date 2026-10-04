from __future__ import annotations

import pathlib
import tempfile
from typing import Any

from evaluations import _run_driver
from evaluations.ablation_driver import (
    PUBLISHED_BASELINES,
    PUBLISHED_BASELINES_UNQUANTIFIED,
    run_ablation_sweep,
)
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
    _run_driver.configure_environment(db_path, str(tmp / "cache"), live=False)
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
        assert (
            record["evaluation_identity"]
            == (by_run[record["run_id"]]["evaluation_identity"])
        )


def test_ablation_records_carry_real_floats_ablation_summary_requires() -> None:
    report = run_ablation_sweep(_GOALS, "express", live=False, arms=_ARMS)
    for record in report["records"]:
        assert isinstance(record["cost_usd"], float)
        assert isinstance(record["latency_seconds"], float)
        assert isinstance(record["diversity"], float)
        assert record["cost_usd"] == 0.0, "offline calls must cost nothing"


def test_no_meta_review_arm_completes_and_disables_the_flag() -> None:
    # The toggle removes periodic cadence; evolution still enters the meta-
    # review node.
    arm, db_path = _drive_one_arm({"enable_meta_review": False})
    assert arm["completed"], arm
    state = _persisted_state(arm["run_id"], db_path)
    assert state["enable_meta_review"] is False


def test_debate_only_arm_completes_and_forces_the_strategy() -> None:
    arm, db_path = _drive_one_arm({"generation_strategy": "no_lit"})
    assert arm["completed"], arm
    state = _persisted_state(arm["run_id"], db_path)
    assert state["generation_strategy"] == "no_lit"


def test_documents_the_now_reachable_and_residual_unreachable_arms() -> None:
    report = run_ablation_sweep(_GOALS, "express", live=False, arms=_ARMS)
    assert {"no_meta_review", "debate_only_strategy"} <= set(report["arms_run"])
    assert "no_meta_review" not in report["unreachable_arms"]
    assert "no_debate_strategy" not in report["unreachable_arms"]
    assert "no_evolution" in report["unreachable_arms"]


def test_published_baselines_cover_reflection_evolution_meta_review() -> None:
    assert set(PUBLISHED_BASELINES) == {
        "reflection_search_tool",
        "evolution",
        "meta_review",
    }
    reflection = PUBLISHED_BASELINES["reflection_search_tool"]
    assert reflection["metrics"]["novelty"] == {
        "baseline": 6.14,
        "ablated": 2.38,
    }
    assert (
        reflection["metrics"]["correctness"]["baseline"]
        < (reflection["metrics"]["correctness"]["ablated"])
    )
    assert (
        reflection["metrics"]["novelty"]["baseline"]
        > (reflection["metrics"]["novelty"]["ablated"])
    )


def test_published_baselines_unquantified_names_ranking_and_proximity() -> None:
    assert set(PUBLISHED_BASELINES_UNQUANTIFIED) == {
        "ranking_prompt",
        "proximity",
    }


def test_published_baselines_are_carried_in_the_report_unmodified() -> None:
    # Reference baselines are report data and must not feed computed arm
    # summaries.
    report = run_ablation_sweep(_GOALS, "express", live=False, arms=_ARMS)
    assert report["published_baselines"] == PUBLISHED_BASELINES
    assert (
        report["published_baselines_unquantified"]
        == PUBLISHED_BASELINES_UNQUANTIFIED
    )
    assert "published_baselines" not in report["summary"]


def test_offline_budget_curve_orders_tiers_by_compute() -> None:
    report = run_budget_curve(
        "Explain a plausible mechanism of antibiotic tolerance in "
        "biofilm-embedded bacteria.",
        ["express", "standard"],
        live=False,
    )

    assert report["mode"] == "offline"
    assert report["offline_disclaimer"]
    assert len(report["arms"]) == 2
    for arm in report["arms"]:
        assert arm["completed"], arm
        assert arm["used_real_backend"] is False

    curve = report["curve"]
    assert curve[0]["hypothesis_count"] <= curve[1]["hypothesis_count"]
    assert curve[0]["compute"]["llm_calls"] <= curve[1]["compute"]["llm_calls"]
    for point in curve:
        assert point["cost_usd"] == 0.0, "offline calls must cost nothing"
        assert (
            point["latency_seconds"] is not None
            and point["latency_seconds"] > 0
        )


def test_offline_snapshots_carry_claim_counts_scaling_eval_expects() -> None:
    report = run_budget_curve(
        "Explain a plausible mechanism of antibiotic tolerance in "
        "biofilm-embedded bacteria.",
        ["express"],
        live=False,
    )
    snapshot = report["snapshots"][0]
    assert snapshot["goal_id"] == report["goal_id"]
    assert (
        snapshot["evaluation_identity"]
        == report["arms"][0]["evaluation_identity"]
    )
    assert snapshot["evaluation_identity"]["cache_policy"] == "disabled"
    for hypothesis in snapshot["hypotheses"]:
        assert "text" in hypothesis
        assert "elo_rating" in hypothesis
        assert isinstance(hypothesis["assessed_claims"], int)
        assert isinstance(hypothesis["verified_claims"], int)


def test_offline_snapshot_carries_a_real_temporal_curve() -> None:
    report = run_budget_curve(
        "Explain a plausible mechanism of antibiotic tolerance in "
        "biofilm-embedded bacteria.",
        ["express"],
        live=False,
    )
    snapshot = report["snapshots"][0]
    curve = snapshot["temporal_curve"]
    generations = {h["generation"] for h in snapshot["hypotheses"]}
    cycles = {h["creation_iteration"] for h in snapshot["hypotheses"]}

    assert curve, "an express run must produce at least one hypothesis"
    assert len(curve) <= 10
    assert sum(b["n_hypotheses"] for b in curve) == len(snapshot["hypotheses"])
    assert len(cycles) >= 2, (
        "express still runs one evolution round -- creation_iteration must "
        "vary end to end (engine stamp -> drain -> store -> eval) or the "
        "temporal curve orders nothing real"
    )
    assert len(generations) >= 2, (
        "express still runs one evolution round -- generation (the fallback "
        "axis) must vary too"
    )
    for bucket in curve:
        assert bucket["best_elo"] is not None, "offline run always rates"
        assert bucket["of"] == len(curve)
