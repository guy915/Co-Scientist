"""Golden acceptance cannot spend on tools outside campaign qualification."""

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_golden_run_rejects_unqualified_indra_before_execution(
    tmp_path: Path,
) -> None:
    script = """
import os
from unittest.mock import patch
from evaluations.golden_run import run
with patch("evaluations.golden_run._install_tool_call_counter",
           side_effect=AssertionError("execution started before admission")):
    try:
        run()
    except RuntimeError as error:
        assert "INDRA" in str(error), str(error)
    else:
        raise AssertionError("unqualified INDRA accepted")
assert os.environ["COSCIENTIST_REQUIRE_FREE_MODELS"] == "1"
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(_ROOT),
            "COSCIENTIST_REQUIRE_FREE_MODELS": "1",
            "MODEL_NAME": "openrouter/campaign/zero:free",
            "OPENROUTER_API_KEY": "synthetic-router",
            "DEEPSEEK_API_KEY": "synthetic-paid",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_explicit_noncampaign_golden_uses_no_dotenv_defaults(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text(
        "GEMINI_API_KEY=synthetic-paid\nMODEL_NAME=deepseek/implicit\n"
    )
    script = """
import os
from unittest.mock import patch
from evaluations.golden_run import run

def observe_config():
    from app.config import settings
    assert settings.gemini_api_key == ""
    for model in (settings.model_name, settings.supervisor_model_name,
                  settings.chat_model_name, settings.semantic_safety_model,
                  settings.claim_verifier_model):
        assert model == "openrouter/explicit/model"
    assert settings.tools_config.endswith("indra_cancer.yaml")
    assert settings.claim_assessor == "llm"
    raise RuntimeError("configuration observed; no execution")

with patch("evaluations.golden_run._install_tool_call_counter", observe_config):
    try:
        run()
    except RuntimeError as error:
        assert str(error) == "configuration observed; no execution"
    else:
        raise AssertionError("unexpected execution")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(_ROOT),
            "MODEL_NAME": "openrouter/explicit/model",
            "OPENROUTER_API_KEY": "synthetic-router",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
