"""Recovery cannot substitute old incomplete evidence or rewrite original receipts."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from comparison_recovery import validate_execution_sources

FOLDER = Path(__file__).resolve().parent


def test_historical_execution_is_verified_against_recorded_git_bytes():
    catalog = json.loads((FOLDER / "opposition-scope-pro-catalog-1.json").read_text())
    validate_execution_sources(FOLDER, catalog, recovered=False)
    catalog["execution_sources"]["run_retrieval_trials.py"] = "0" * 64
    with pytest.raises(ValueError, match="execution"):
        validate_execution_sources(FOLDER, catalog, recovered=False)


def test_missing_replacement_does_not_fall_back_or_overwrite_original_summary(tmp_path):
    import shutil

    for name in (
        "opposition-scope-pro-paired-summary.json",
        "opposition-scope-pro-baseline-1.json",
        "opposition-scope-pro-candidate-1.json",
        "opposition-scope-pro-catalog-1.json",
        "scope-preflight.json",
        "scope_controls.py",
        "partial-support-scope-controls.json",
        "probe_citation_panel.py",
        "qualification_sources.py",
    ):
        shutil.copy(FOLDER / name, tmp_path / name)
    # Historical recovery fixtures must use the observer pinned by their manifest.
    (tmp_path / "scope_controls.py").write_bytes(
        subprocess.check_output(
            [
                "git",
                "show",
                "c8a11d511268616ade139d217ffae2762a2a5da9:references/external/baseline/model-qualification/scope_controls.py",
            ],
            cwd=FOLDER.parents[3],
        )
    )
    original = tmp_path / "opposition-scope-pro-paired-summary.json"
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    result = subprocess.run(
        [
            sys.executable,
            str(FOLDER / "compare_opposition_panels.py"),
            "--series",
            "opposition-scope-pro",
            "--attempt",
            "recovery1",
            "--artifact-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Missing recovery artifacts for trial 2" in result.stderr
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before


def test_recovery_requires_pinned_orchestration_and_frozen_scientific_observers():
    catalog = json.loads(
        (FOLDER / "opposition-scope-pro-catalog-2-recovery1.json").read_text()
    )
    validate_execution_sources(FOLDER, catalog, recovered=True)
    catalog["execution_sources"]["run_retrieval_trials.py"] = "0" * 64
    with pytest.raises(ValueError, match="execution"):
        validate_execution_sources(FOLDER, catalog, recovered=True)
    catalog = json.loads(
        (FOLDER / "opposition-scope-pro-catalog-2-recovery1.json").read_text()
    )
    catalog["execution_sources"]["probe_citation_panel.py"] = "0" * 64
    with pytest.raises(ValueError, match="execution"):
        validate_execution_sources(FOLDER, catalog, recovered=True)


def test_recovery_catalog_retains_original_hashes_and_missing_arm(tmp_path):
    from comparison_recovery import validate_recovery_catalog

    baseline = tmp_path / "opposition-scope-pro-baseline-3.json"
    baseline.write_text("retained original\n")
    catalog = {
        "attempt": "recovery1",
        "selected_trials": [2, 3],
        "source_manifest_sha256": "frozen",
        "recovery_of": [
            {
                "path": baseline.name,
                "sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
                "status": "retained",
            },
            {
                "path": "opposition-scope-pro-candidate-3.json",
                "sha256": None,
                "status": "missing_after_interruption",
            },
        ],
    }
    validate_recovery_catalog(tmp_path, catalog, 3, "frozen")
    baseline.write_text("changed original\n")
    with pytest.raises(ValueError, match="Original recovery evidence"):
        validate_recovery_catalog(tmp_path, catalog, 3, "frozen")
