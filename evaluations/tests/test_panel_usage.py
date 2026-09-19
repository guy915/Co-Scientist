"""Live panel artifacts retain physical provider observations."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("panel", ["usefulness", "citation", "elo"])
def test_panel_artifact_records_served_model_and_unknown_price(
    tmp_path: Path,
    panel: str,
) -> None:
    script = """
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
              "content": json.dumps(payloads[panel])},
              "finish_reason": "stop"}],
    usage={"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10})
provider = AsyncMock(return_value=response)
with patch.object(httpx, "get", return_value=metadata), \
     patch.object(litellm, "acompletion", provider):
    if panel == "usefulness":
        report = citation_usefulness_eval.run_llm({"name": "probe",
            "items": [{"id": "one", "question": "Does X inhibit Y?",
                "span": "X inhibits Y.", "label": "useful"}]})
    elif panel == "citation":
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
assert report["execution_mode"] == "live_requested"
evidence = report["usage_evidence"]
assert evidence["physical_calls"] == 1
assert evidence["observed_models"] == ["openrouter/campaign/served:free"]
assert evidence["requested_models"] == {"openrouter/campaign/primary:free": 1}
assert evidence["estimated_total_usd"] is None
assert evidence["billed_total_usd"] is None
if panel == "elo":
    live = report["results"]["llm:openrouter/campaign/primary:free"]
    assert live["execution_mode"] == "live_requested"
    assert live["usage_evidence"] == evidence
    for name in ("correctness_preferring", "inverting", "coin_flip_seed0"):
        assert report["results"][name]["execution_mode"] == "offline"
else:
    assert report["metrics"]["accuracy"] == 1.0
assert provider.call_args.kwargs["extra_body"]["provider"]["max_price"] == {
    "prompt": 0, "completion": 0, "request": 0}
"""
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
        citation_usefulness_eval.run_deterministic(
            {"name": "empty", "items": []}
        ),
        elo_concordance_eval.run(use_llm=False),
    ]
    for report in reports:
        assert report["execution_mode"] == "offline"
        assert report["usage_evidence"] is None
    assert all(
        result["execution_mode"] == "offline"
        for result in reports[-1]["results"].values()
    )
