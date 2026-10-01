"""Durable artifacts distinguish unknown cost from a zero estimate."""

from pathlib import Path

from evaluations._run_driver import compute_arm_metrics
from evaluations.golden_run import _cost_summary


def test_golden_artifact_retains_unknown_identity_and_cost() -> None:
    raw = {"phase::requested": {"calls": 2, "cost_usd": 0.0}}
    report = _cost_summary({"model_usage": raw})
    evidence = report["usage_evidence"]
    assert evidence["model_usage"] == raw
    assert evidence["observed_models"] == []
    assert evidence["unobserved_model_calls"] == 2
    assert evidence["unreported_usage_calls"] == 2
    assert evidence["unpriced_calls"] == 2
    assert evidence["estimated_total_usd"] is None
    assert evidence["billed_total_usd"] is None


def test_durable_artifact_retains_requested_and_observed_models(
    tmp_path: Path,
) -> None:
    from app import store

    db = str(tmp_path / "metrics.db")
    run = store.create_run(
        "public evidence",
        "express",
        "engine",
        {},
        store.RunCreateOptions(db_path=db, llm_backend="real"),
    )
    raw = {
        "judge::openrouter/served": {
            "calls": 1,
            "observed_model_calls": 1,
            "reported_usage_calls": 1,
            "priced_usage_calls": 1,
            "requested_models": {"openrouter/asked": 1},
            "prompt_tokens": 7,
            "completion_tokens": 3,
            "cost_usd": 0.0,
        }
    }
    raw["judge::openrouter/asked"] = {
        "calls": 0,
        "deterministic_fallbacks": {"claim_batch": 1},
    }
    store.save_run_metrics(run.id, {"model_usage": raw}, db_path=db)
    report = compute_arm_metrics(run.id, db, 0.5, 1)
    evidence = report["usage_evidence"]
    assert evidence["model_usage"] == raw
    assert evidence["recorded_deterministic_fallbacks"] == {"claim_batch": 1}
    assert evidence["fallback_evidence"] == "recorded_events_only"
    assert evidence["observed_models"] == ["openrouter/served"]
    assert evidence["requested_models"] == {"openrouter/asked": 1}
    assert evidence["estimated_total_usd"] == 0.0
    assert evidence["billed_total_usd"] is None
    assert report["cost_basis"] == "partial_static_estimate"
    from evaluations.claim_support_eval import score_run

    scored = score_run(run.id, db_path=db)
    assert scored["configured_backend"] == "real"
    assert scored["usage_evidence"] == evidence


def test_derived_curves_preserve_unknown_costs() -> None:
    from evaluations.scaling_eval import ablation_summary, scaling_curve

    evidence = {"estimated_total_usd": None, "estimate_complete": False}
    metrics = {"cost_usd": 0.0, "usage_evidence": evidence}
    curve = scaling_curve([{"hypotheses": [], "metrics": metrics}])
    assert curve[0]["usage_evidence"] == evidence
    base = {
        "arm": "baseline",
        "goal_id": "public",
        "diversity": 0.5,
        "cost_usd": 0.0,
        "latency_seconds": 1,
        "usage_evidence": evidence,
    }
    summary = ablation_summary([base])["arms"]["baseline"]
    assert summary["estimated_mean_usd"] is None
    base["usage_evidence"] = {
        "estimate_complete": True,
        "estimated_total_usd": 0.0,
    }
    summary = ablation_summary([base])["arms"]["baseline"]
    assert summary["estimated_mean_usd"] == 0.0


def test_missing_cost_value_cannot_be_a_complete_zero_estimate() -> None:
    from evaluations._usage_evidence import summarize_usage

    report = summarize_usage(
        {
            "phase::model": {
                "calls": 1,
                "observed_model_calls": 1,
                "reported_usage_calls": 1,
                "priced_usage_calls": 1,
            }
        }
    )
    assert report["estimated_total_usd"] is None
    assert report["unpriced_calls"] == 1
    assert summarize_usage({})["estimated_total_usd"] is None


def test_overclaimed_observations_cannot_complete_cost_evidence() -> None:
    from evaluations._usage_evidence import summarize_usage

    report = summarize_usage(
        {
            "phase::model": {
                "calls": 1,
                "observed_model_calls": 2,
                "reported_usage_calls": 1,
                "priced_usage_calls": 1,
                "cost_usd": 0,
            }
        }
    )
    assert report["estimated_total_usd"] is None


def test_durable_merge_retains_events_without_claiming_complete_tracking() -> (
    None
):
    import json

    from co_scientist.models.metrics import ExecutionMetrics, merge_metrics

    legacy = ExecutionMetrics(model_usage={"judge::model": {"calls": 2}})
    delta = ExecutionMetrics(
        model_usage={
            "judge::model": {
                "calls": 1,
                "deterministic_fallbacks": {"claim_single": 1},
            }
        }
    )
    combined = merge_metrics(merge_metrics(legacy, delta), delta)
    checkpoint = json.loads(json.dumps(combined.model_usage))
    evidence = _cost_summary({"model_usage": checkpoint})["usage_evidence"]
    assert evidence["physical_calls"] == 4
    assert evidence["recorded_deterministic_fallbacks"] == {"claim_single": 2}
    assert evidence["fallback_evidence"] == "recorded_events_only"
    old = _cost_summary({"model_usage": legacy.model_usage})["usage_evidence"]
    assert old["recorded_deterministic_fallbacks"] == {}
    assert old["fallback_evidence"] == "recorded_events_only"
