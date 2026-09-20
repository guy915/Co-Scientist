"""Verify historical observers and explicit replacement provenance without inference."""

import hashlib
import subprocess

HISTORICAL_REVISION = "9acebec9"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_execution_sources(folder, catalog, *, recovered):
    scientific = ("probe_citation_panel.py", "qualification_sources.py")
    orchestration = ("run_retrieval_trials.py", "compare_opposition_panels.py")
    for name in scientific + orchestration:
        if recovered and name in orchestration:
            expected = digest(folder / name)
        else:
            relative = (folder / name).relative_to(folder.parents[3])
            content = subprocess.check_output(
                ["git", "show", f"{HISTORICAL_REVISION}:{relative}"],
                cwd=folder.parents[3],
            )
            expected = hashlib.sha256(content).hexdigest()
        if catalog["execution_sources"].get(name) != expected:
            raise ValueError("Recorded execution source differs: " + name)
        if name in scientific and digest(folder / name) != expected:
            raise ValueError("Frozen scientific observer changed: " + name)
    if recovered:
        for name in ("recovery_schedule.py", "comparison_recovery.py"):
            if catalog["execution_sources"].get(name) != digest(folder / name):
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
