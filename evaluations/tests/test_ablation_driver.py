"""Controlled feature-ablation driver tests (L11).

Runs the offline path only: proving the driver's wiring, per-arm record
shape, and ``ablation_summary`` pairing end to end without a provider key or
network -- including that the two engine-side toggles this row added
(``enable_meta_review``, ``generation_strategy``) reach the engine's
persisted workflow state and the run still completes. The live sweep (where
the toggles actually change literature/tool/meta-review behavior) is the
operator's explicit ``--live`` invocation, never run here -- see the module
docstring for why an offline run cannot show a real ablation effect. Offline
arms are identical by construction, so these assert wiring, not effect.
"""

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
    """Drive a single offline arm and return (arm detail, db_path).

    Bypasses ``run_ablation_sweep`` so the test can read the arm run's
    persisted checkpoint back off the same db and prove the toggle
    round-tripped into engine state, not merely into the run config.
    """
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
    """Return the run's latest checkpoint's deserialized workflow state."""
    from app import store

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


def test_ablation_records_carry_real_floats_ablation_summary_requires() -> None:
    """``ablation_summary`` reads cost/latency/diversity unconditionally.

    A None here would raise inside ``ablation_summary`` -- see its
    ``float(item["cost_usd"])`` etc, which are not None-guarded the way
    ``expert_quality``/``verified_claim_ratio`` are.
    """
    report = run_ablation_sweep(_GOALS, "express", live=False, arms=_ARMS)
    for record in report["records"]:
        assert isinstance(record["cost_usd"], float)
        assert isinstance(record["latency_seconds"], float)
        assert isinstance(record["diversity"], float)
        assert record["cost_usd"] == 0.0, "offline calls must cost nothing"


def test_no_meta_review_arm_completes_and_disables_the_flag() -> None:
    """The meta-review toggle reaches engine state and the run still ends.

    Reads the persisted checkpoint rather than the run config, so this
    proves the opt threaded all the way into the workflow state the
    scheduler's cadence check reads. Not asserting "zero meta_review
    tasks": the EVOLVE branch still enters that node, so this arm removes
    the *periodic* cadence, not the node (see the driver docstring).
    """
    arm, db_path = _drive_one_arm({"enable_meta_review": False})
    assert arm["completed"], arm
    state = _persisted_state(arm["run_id"], db_path)
    assert state["enable_meta_review"] is False


def test_debate_only_arm_completes_and_forces_the_strategy() -> None:
    """The generation-strategy toggle reaches engine state and completes."""
    arm, db_path = _drive_one_arm({"generation_strategy": "no_lit"})
    assert arm["completed"], arm
    state = _persisted_state(arm["run_id"], db_path)
    assert state["generation_strategy"] == "no_lit"


def test_documents_the_now_reachable_and_residual_unreachable_arms() -> None:
    """Meta-review and debate-strategy are now driveable arms.

    They used to live in ``unreachable_arms`` (no engine switch existed);
    this row built the switches, so they are ordinary arms now. The one
    arm still genuinely unreachable -- the Evolution agent, which no config
    toggle disables -- stays documented so its absence is not silent.
    """
    report = run_ablation_sweep(_GOALS, "express", live=False, arms=_ARMS)
    assert {"no_meta_review", "debate_only_strategy"} <= set(report["arms_run"])
    assert "no_meta_review" not in report["unreachable_arms"]
    assert "no_debate_strategy" not in report["unreachable_arms"]
    assert "no_evolution" in report["unreachable_arms"]


def test_published_baselines_cover_reflection_evolution_meta_review() -> None:
    """Google's ablation numbers (R11-8) cover the arms.

    Plus the reachable Reflection search-tool arm.
    """
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
    # Not uniformly directional: correctness improves while novelty
    # collapses. Both numbers must survive, never smoothed into one story.
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
    """Reference data only, never fed into the computed ``summary``.

    ``summary`` reads only the driven ``records``.
    """
    report = run_ablation_sweep(_GOALS, "express", live=False, arms=_ARMS)
    assert report["published_baselines"] == PUBLISHED_BASELINES
    assert (
        report["published_baselines_unquantified"]
        == PUBLISHED_BASELINES_UNQUANTIFIED
    )
    assert "published_baselines" not in report["summary"]
