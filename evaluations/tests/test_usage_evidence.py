from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from evaluations._run_driver import compute_arm_metrics
from evaluations._usage_evidence import summarize_usage
from evaluations.tests._engine_fake_backend import SCRIPT_PRELUDE


def test_durable_artifact_retains_requested_and_observed_models(
    tmp_path: Path,
) -> None:
    from app.store import retrieval_calls as store
    from app.store import runs
    from app.store.runs import RunCreateOptions

    db = str(tmp_path / "metrics.db")
    run = runs.create_run(
        "public evidence",
        "express",
        "engine",
        {},
        RunCreateOptions(db_path=db, llm_backend="real"),
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


@pytest.mark.parametrize(
    ("usage", "unpriced"),
    [
        ({}, None),
        ({"phase::requested": {"calls": 2, "cost_usd": 0.0}}, 2),
        (
            {
                "phase::model": {
                    "calls": 1,
                    "observed_model_calls": 1,
                    "reported_usage_calls": 1,
                    "priced_usage_calls": 1,
                }
            },
            1,
        ),
        (
            {
                "phase::model": {
                    "calls": 1,
                    "observed_model_calls": 2,
                    "reported_usage_calls": 1,
                    "priced_usage_calls": 1,
                    "cost_usd": 0,
                }
            },
            None,
        ),
    ],
)
def test_unknown_or_overclaimed_usage_cannot_be_a_complete_zero_estimate(
    usage: dict[str, Any], unpriced: int | None
) -> None:
    report = summarize_usage(usage)
    assert report["estimated_total_usd"] is None
    assert report["billed_total_usd"] is None
    if unpriced is not None:
        assert report["unpriced_calls"] == unpriced


_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("panel", ["usefulness", "citation", "elo", "citation_failure"])
def test_panel_artifact_records_served_model_and_unknown_price(
    tmp_path: Path,
    panel: str,
) -> None:
    script = (
        SCRIPT_PRELUDE
        + """
from unittest.mock import AsyncMock, patch
import httpx
import litellm
import json
from pathlib import Path
from evaluations import citation_eval, citation_usefulness_eval
from evaluations import elo_concordance_eval
panel = __PANEL__
passage = "Kinase X inhibition reduces tumor growth in AML cell lines."
payloads = {
    "usefulness": {"label": "useful"},
    "citation": {"label": "supports", "supporting": [{"passage": 1,
        "quote": passage}],
        "contradicting": []},
    "elo": {"winner": "a", "decision_summary": "Candidate A is correct.",
        "confidence_level": "High"},
}

catalog = {"data": [{"id": "campaign/primary:free",
    "pricing": {"prompt": "0", "completion": "0"},
    "architecture": {"input_modalities": ["text"],
                     "output_modalities": ["text"]}}]}
metadata = httpx.Response(200, json=catalog,
    request=httpx.Request("GET", "https://openrouter.ai/api/v1/models"))
response = litellm.ModelResponse(model="campaign/served:free",
    choices=[{"message": {"role": "assistant",
              "content": json.dumps(payloads.get(panel, {}))},
              "finish_reason": "stop"}],
    usage={"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10})
provider = AsyncMock(return_value=response)
if panel == "citation_failure":
    provider.side_effect = RuntimeError("offline test provider failure")
with patch.object(httpx, "get", return_value=metadata), \
     fake_backend(provider):
    if panel == "usefulness":
        report = citation_usefulness_eval.run_llm({"name": "probe",
            "items": [{"id": "one", "question": "Does X inhibit Y?",
                "span": "X inhibits Y.", "label": "useful"}]})
    elif panel.startswith("citation"):
        dataset = Path("citation.json")
        dataset.write_text(json.dumps({"name": "probe", "version": 1,
            "items": [{"claim": "Kinase X inhibition reduces tumor growth",
                "passages": [passage],
                "label": "supports"}]}))
        report = citation_eval.run(use_llm=True, dataset_path=dataset)
    else:
        dataset = {"name": "probe", "version": 1, "items": [{"id": "one",
            "domain": "physics", "question": "What is two plus two?",
            "candidates": [{"id": "a", "text": "Four", "correctness": 2},
                           {"id": "b", "text": "Five", "correctness": 0}]}]}
        with patch.object(elo_concordance_eval, "_load_dataset",
                          return_value=dataset):
            report = elo_concordance_eval.run(use_llm=True)
assert report["evaluation_identity"]["kind"] == "panel"
assert report["evaluation_identity"]["model"] == (
    "openrouter/campaign/primary:free")
assert report["execution_mode"] == "live_requested"
evidence = report["usage_evidence"]
calls = 3 if panel == "citation_failure" else 1
observed = [] if panel == "citation_failure" else [
    "openrouter/campaign/served:free"]
assert evidence["physical_calls"] == calls
assert evidence["observed_models"] == observed
assert evidence["requested_models"] == {
    "openrouter/campaign/primary:free": calls}
assert evidence["recorded_deterministic_fallbacks"] == (
    {"claim_single": 1} if panel == "citation_failure" else {})
assert evidence["fallback_evidence"] == "recorded_events_only"
assert evidence["estimated_total_usd"] is None
assert evidence["billed_total_usd"] is None
if panel == "elo":
    live = report["results"]["llm:openrouter/campaign/primary:free"]
    assert live["usage_evidence"] == evidence
else:
    assert report["metrics"]["accuracy"] == 1.0
assert provider.call_args.kwargs["extra_body"]["provider"]["max_price"] == {
    "prompt": 0, "completion": 0, "request": 0}
"""
    )
    script = script.replace("__PANEL__", repr(panel))
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(_ROOT),
            "PYTHON_DOTENV_DISABLED": "1",
            "MODEL_NAME": "openrouter/campaign/primary:free",
            "OPENROUTER_API_KEY": "synthetic-router",
        },
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr


def test_offline_panels_do_not_claim_live_usage() -> None:
    from evaluations import (
        citation_eval,
        citation_usefulness_eval,
        elo_concordance_eval,
    )

    reports = [
        citation_eval.run(),
        citation_usefulness_eval.run_deterministic({"name": "empty", "items": []}),
        elo_concordance_eval.run(use_llm=False),
    ]
    for report in reports:
        assert report["evaluation_identity"]["kind"] == "panel"
        assert report["evaluation_identity"]["execution_mode"] == "offline"
        assert report["execution_mode"] == "offline"
        assert report["usage_evidence"] is None
    assert all(result["execution_mode"] == "offline" for result in reports[-1]["results"].values())


@pytest.mark.parametrize(
    "invocation",
    [
        "citation_eval.run(use_llm=True)",
        "elo_concordance_eval.run(use_llm=True)",
        'citation_usefulness_eval.run_llm({"name": "empty", "items": []}, "")',
        'citation_usefulness_eval.run_llm({}, "deepseek/paid")',
    ],
)
def test_panels_reject_implicit_models_before_judging(tmp_path: Path, invocation: str) -> None:
    module = invocation.split(".", 1)[0]
    script = f"""
import sys
from evaluations import {module}
assert "co_scientist" not in sys.modules
try:
    {invocation}
except ValueError as error:
    assert "MODEL_NAME" in str(error), str(error)
else:
    raise AssertionError("implicit model accepted")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={"PATH": os.environ["PATH"], "PYTHONPATH": str(_ROOT)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
