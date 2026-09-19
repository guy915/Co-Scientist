"""Public report comparisons require frozen, matched panel controls."""

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from evaluations.citation_usefulness_eval import run_deterministic


def _compare(
    tmp_path: Path, left: dict[str, Any], right: dict[str, Any]
) -> subprocess.CompletedProcess[str]:
    paths = [tmp_path / "baseline.json", tmp_path / "candidate.json"]
    for path, report in zip(paths, (left, right), strict=True):
        path.write_text(json.dumps(report))
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "evaluations.panel_comparison",
            *map(str, paths),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_matched_panel_reports_are_comparable(tmp_path: Path) -> None:
    report = run_deterministic({"name": "frozen", "items": []})
    result = _compare(tmp_path, report, report)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "matched_declared_inputs"


@pytest.mark.parametrize(
    "change", ["dataset", "missing", "mode", "kind", "incomplete"]
)
def test_changed_panel_controls_are_rejected(
    tmp_path: Path, change: str
) -> None:
    report = run_deterministic({"name": "frozen", "items": []})
    candidate = copy.deepcopy(report)
    if change == "dataset":
        candidate = run_deterministic({"name": "different", "items": []})
    elif change == "missing":
        candidate.pop("evaluation_identity")
    elif change == "mode":
        candidate["execution_mode"] = "live_requested"
    else:
        _reseal_invalid_pair(report, candidate, change)
    result = _compare(tmp_path, report, candidate)
    assert result.returncode != 0
    assert "ValueError" in result.stderr


def _reseal_invalid_pair(
    report: dict[str, Any], candidate: dict[str, Any], change: str
) -> None:
    from evaluations._comparison_identity import identity_digest

    for artifact in (report, candidate):
        identity = artifact["evaluation_identity"]
        identity.pop("digest")
        if change == "incomplete":
            identity.pop("dataset")
        else:
            identity["kind"] = "arm"
        identity["digest"] = identity_digest(identity)
