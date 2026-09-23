"""Live scientific panels require explicit campaign configuration."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "invocation",
    [
        "citation_eval._build_llm_assessor()",
        "citation_eval.run(use_llm=True)",
        "elo_concordance_eval._make_llm_comparator()",
        "elo_concordance_eval.run(use_llm=True)",
        'citation_usefulness_eval.run_llm({"name": "empty", "items": []}, "")',
        'citation_usefulness_eval.run_llm({}, "deepseek/paid")',
    ],
)
def test_panels_reject_implicit_models_before_judging(
    tmp_path: Path, invocation: str
) -> None:
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
