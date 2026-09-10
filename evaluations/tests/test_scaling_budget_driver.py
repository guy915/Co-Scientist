"""Controlled multi-budget scaling-curve driver tests (L9).

Runs the offline path only: a real (deterministic, offline-backed) durable
run per tier, proving the driver's wiring end-to-end without a provider key
or network. This is the cheap, hermetic path CI exercises; the live
multi-tier sweep is the operator's explicit ``--live`` invocation (see the
module docstring), never run here.
"""

from __future__ import annotations

from evaluations.scaling_budget_driver import run_budget_curve


def test_offline_budget_curve_orders_tiers_by_compute() -> None:
    """Two tiers, run offline, produce an ordered curve with real shape.

    ``express`` requests strictly less compute than ``standard`` in every
    tier default (hypotheses/tournament pairs/evidence/max_llm_calls), so a
    genuinely-wired driver must place express first regardless of content.
    """
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
    """Each hypothesis in a snapshot has the fields ``scaling_curve`` reads."""
    report = run_budget_curve(
        "Explain a plausible mechanism of antibiotic tolerance in "
        "biofilm-embedded bacteria.",
        ["express"],
        live=False,
    )
    snapshot = report["snapshots"][0]
    assert snapshot["goal_id"] == report["goal_id"]
    for hypothesis in snapshot["hypotheses"]:
        assert "text" in hypothesis
        assert "elo_rating" in hypothesis
        assert isinstance(hypothesis["assessed_claims"], int)
        assert isinstance(hypothesis["verified_claims"], int)


def test_offline_snapshot_carries_a_real_temporal_curve() -> None:
    """R1-13: each arm's own within-run temporal curve, from a real run.

    Express requests 4 initial hypotheses (fewer than the published
    method's 10 buckets), so this also exercises the "fewer than ten
    hypotheses" degenerate case against a genuine offline durable run
    rather than only synthetic dicts.

    Also asserts the ordering signal actually varies, end to end from a real
    offline durable run: ``creation_iteration`` (the authoring-cycle axis the
    engine stamps, the drain persists, and the eval buckets by) and its
    ``generation`` fallback must each span at least two values, or a passing
    curve would not prove the bucketing tracks anything temporal rather than
    an arbitrary, flat order -- see ``scaling_eval._temporal_order_key`` for
    why ``created_at`` alone does not carry it.
    """
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
