"""Recovery keeps paired ordering and cannot overwrite an original attempt."""

import pytest

from recovery_schedule import schedule

ORDER = [
    ["baseline", "candidate"],
    ["candidate", "baseline"],
    ["baseline", "candidate"],
]


def test_incomplete_pairs_keep_original_order_and_separate_names():
    assert schedule(ORDER, [2, 3], "recovery1") == [
        (2, ["candidate", "baseline"], "-recovery1"),
        (3, ["baseline", "candidate"], "-recovery1"),
    ]


@pytest.mark.parametrize(
    "trials,attempt",
    [
        ([2], ""),
        ([2, 2], "recovery1"),
        ([4], "recovery1"),
        ([2], "../old"),
        ([], "recovery1"),
    ],
)
def test_invalid_recovery_cannot_name_outputs(trials, attempt):
    with pytest.raises(ValueError):
        schedule(ORDER, trials, attempt)


def test_original_schedule_keeps_original_names():
    assert schedule(ORDER, [1, 2, 3], "") == [
        (1, ["baseline", "candidate"], ""),
        (2, ["candidate", "baseline"], ""),
        (3, ["baseline", "candidate"], ""),
    ]


def test_runner_plan_is_offline_and_refuses_existing_recovery_log(tmp_path):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys

    folder = Path(__file__).resolve().parent
    frozen = json.loads((folder / "scope-preflight.json").read_text())[
        "source_manifest"
    ]
    manifest = tmp_path / "source-manifest.json"
    manifest.write_text(json.dumps(frozen, indent=2) + "\n")
    command = [
        sys.executable,
        str(folder / "run_retrieval_trials.py"),
        str(manifest),
        "--trials",
        "2",
        "3",
        "--attempt",
        "recovery1",
        "--plan-only",
    ]
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["inference_performed"] is False
    assert plan["schedule"] == [
        [2, ["candidate", "baseline"], "-recovery1"],
        [3, ["baseline", "candidate"], "-recovery1"],
    ]
    collision = tmp_path / "candidate-2-recovery1.log"
    collision.write_text("original evidence\n")
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    assert result.returncode != 0
    assert "Existing trial artifacts" in result.stderr
    assert collision.read_text() == "original evidence\n"
