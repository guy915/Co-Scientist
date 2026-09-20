"""Verify historical observers and explicit replacement provenance without inference."""

import hashlib
import subprocess
from pathlib import Path

HISTORICAL_REVISION = "9acebec9"
RECOVERY_REVISION = "f052d77a"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_execution_sources(folder, catalog, *, recovered):
    repository = Path(__file__).resolve().parents[4]
    relative_folder = Path(__file__).resolve().parent.relative_to(repository)
    scientific = ("probe_citation_panel.py", "qualification_sources.py")
    orchestration = ("run_retrieval_trials.py", "compare_opposition_panels.py")
    for name in scientific + orchestration:
        relative = relative_folder / name
        revision = (
            RECOVERY_REVISION
            if recovered and name in orchestration
            else HISTORICAL_REVISION
        )
        content = subprocess.check_output(
            ["git", "show", f"{revision}:{relative}"], cwd=repository
        )
        expected = hashlib.sha256(content).hexdigest()
        if catalog["execution_sources"].get(name) != expected:
            raise ValueError("Recorded execution source differs: " + name)
        if name in scientific and digest(folder / name) != expected:
            raise ValueError("Frozen scientific observer changed: " + name)
    if recovered:
        for name in ("recovery_schedule.py", "comparison_recovery.py"):
            relative = relative_folder / name
            content = subprocess.check_output(
                ["git", "show", f"{RECOVERY_REVISION}:{relative}"],
                cwd=repository,
            )
            if (
                catalog["execution_sources"].get(name)
                != hashlib.sha256(content).hexdigest()
            ):
                raise ValueError("Recovery execution source differs: " + name)


def validate_recovery_catalog(folder, catalog, trial, manifest_sha256):
    if (
        catalog.get("attempt") != "recovery1"
        or catalog.get("selected_trials") != [2, 3]
        or catalog.get("source_manifest_sha256") != manifest_sha256
    ):
        raise ValueError("Recovery catalog identity differs")
    order = ("candidate", "baseline") if trial == 2 else ("baseline", "candidate")
    expected = []
    for arm in order:
        path = folder / f"opposition-scope-pro-{arm}-{trial}.json"
        expected.append(
            {
                "path": path.name,
                "sha256": digest(path) if path.exists() else None,
                "status": "retained" if path.exists() else "missing_after_interruption",
            }
        )
    if catalog.get("recovery_of") != expected:
        raise ValueError("Original recovery evidence changed or missing")
