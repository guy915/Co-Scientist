from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

from evaluations import paired_artifacts, paired_quality
from evaluations._identity import identity_digest
from evaluations._paired_db import read_snapshot
from evaluations.quality_goals import GOAL_VERSION, GOALS
from evaluations.tests.test_paired_quality import fake_database


def archive(path: Path, goal_id: str, *, branch: bool = False, change: str = "") -> None:
    db = path.with_suffix(".db")
    fake_database(db, goal_id, branch=branch)
    source, count = ("b" if branch else "a") * 40, 20 if branch else 100
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE evaluation_runs "
            "(run_id, source_commit, physical_requests, request_ceiling)"
        )
        conn.execute("INSERT INTO evaluation_runs VALUES ('r',?,?,200)", (source, count))
        if change == "control":
            config = json.loads(conn.execute("SELECT config_json FROM runs").fetchone()[0])
            identity = config["evaluation_identity"]
            identity["configured_models"]["worker"] = "openrouter/other-free-model"
            identity.pop("digest")
            identity["digest"] = identity_digest(identity)
            conn.execute("UPDATE runs SET config_json=?", (json.dumps(config),))
    snapshot = read_snapshot(db, "r", goal_id, source)
    receipt: dict[str, Any] = {
        "goal_version": GOAL_VERSION,
        "goal_id": goal_id,
        "goal": GOALS[goal_id],
        "source_commit": source,
        "physical_requests_attempted": count,
        "physical_request_ceiling": 200,
        "offline_disclaimer": None,
        "evaluation_identity": snapshot.identity,
        "metrics": snapshot.metrics,
        "provenance": {"source": {"git_commit": source, "git_dirty": False}},
    }
    if change == "count":
        receipt["physical_requests_attempted"] = count + 1
    elif change == "ceiling":
        receipt["physical_request_ceiling"] = 201
    elif change == "offline":
        receipt["offline_disclaimer"] = "offline"
    elif change == "source":
        receipt["source_commit"] = "c" * 40
    elif change == "metric":
        receipt["metrics"]["supported_claims"] = 999
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.write(db, "benchmark-artifacts/snapshot.db")
        if change != "missing":
            bundle.writestr("benchmark-artifacts/receipt.json", json.dumps(receipt))
        if change == "duplicate":
            bundle.writestr("receipt.json", json.dumps(receipt))
        bundle.writestr("../outside.txt", "never extract")


def cohort(tmp_path: Path, *, change: str = "") -> dict[str, list[Path]]:
    arms: dict[str, list[Path]] = {"main": [], "branch": []}
    for arm in arms:
        for index, goal in enumerate(GOALS):
            path = tmp_path / f"{arm}-{index}.zip"
            archive(path, goal, branch=arm == "branch", change=change if index == 0 else "")
            arms[arm].append(path)
    return arms


def test_recorded_archives_replay_full_pipeline_without_network_or_input_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("network call in recorded artifact pipeline")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    arms = cohort(tmp_path)
    hashes = {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for paths in arms.values() for p in paths
    }
    inputs = tmp_path / "archives.json"
    inputs.write_text(json.dumps({a: [p.name for p in paths] for a, paths in arms.items()}))
    output = tmp_path / "replay"
    monkeypatch.setattr(
        sys, "argv", ["paired_artifacts", "--archives", str(inputs), "--output", str(output)]
    )
    assert paired_artifacts.main() == 0
    manifest = output / "prepared/pairs.json"
    exported = output / "packets.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["paired_quality", str(manifest), "--export-packets", "--output", str(exported)],
    )
    assert paired_quality.main() == 0
    judgments = output / "judgments.json"
    judgments.write_text(
        json.dumps(
            {
                key: {"winner": "tie", "rationale": "recorded fake"}
                for key in json.loads(exported.read_text())
            }
        )
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "paired_quality",
            str(manifest),
            "--judgments",
            str(judgments),
            "--output",
            str(output / "paired"),
        ],
    )
    assert paired_quality.main() == 0
    result = json.loads((output / "paired.json").read_text())
    assert result["summary"]["goal_pairs"] == 3
    assert result["summary"]["judge_orders"] == 6
    assert result["judge_physical_requests"] == 0
    assert all(row["main"]["physical_calls"] == 100 for row in result["pairs"])
    assert "inside the noise" in (output / "paired.md").read_text()
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in hashes.items())
    assert not (output / "prepared/outside.txt").exists()


@pytest.mark.parametrize(
    "change", ["count", "ceiling", "offline", "source", "metric", "missing", "duplicate"]
)
def test_inconsistent_or_missing_receipt_fails_before_judging(tmp_path: Path, change: str) -> None:
    with pytest.raises(ValueError):
        paired_artifacts.prepare(cohort(tmp_path, change=change), tmp_path / "prepared")


def test_duplicate_goals_are_rejected(tmp_path: Path) -> None:
    arms = cohort(tmp_path)
    other = tmp_path / "duplicate-goal.zip"
    archive(other, "cell-biology")
    arms["main"][1] = other
    with pytest.raises(ValueError, match="duplicate goal"):
        paired_artifacts.prepare(arms, tmp_path / "prepared")


def test_mismatched_controls_are_rejected_before_judging(tmp_path: Path) -> None:
    arms = cohort(tmp_path)
    changed = tmp_path / "different-controls.zip"
    archive(changed, "cell-biology", branch=True, change="control")
    arms["branch"][0] = changed
    with pytest.raises(ValueError, match="configured_models"):
        paired_artifacts.prepare(arms, tmp_path / "prepared")


def test_malformed_download_ids_and_duplicate_runs_are_rejected_before_network(
    tmp_path: Path,
) -> None:
    for value in ("1,2", "1,2,3,4", "1,2,--help", "1,2,0", "1,2,3/zip"):
        with pytest.raises(ValueError):
            paired_artifacts.parse_run_ids(value)
    with pytest.raises(ValueError, match="distinct"):
        paired_artifacts.download(
            "guy915/Co-Scientist",
            {"main": ["1", "2", "3"], "branch": ["1", "2", "3"]},
            tmp_path / "download",
        )
