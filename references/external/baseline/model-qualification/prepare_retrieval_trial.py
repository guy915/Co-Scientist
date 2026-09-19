"""Prepare and verify pinned comparison snapshots without credentials or inference."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

BASELINE = "14e8c59950204c96cdfa2195594885383d1d5720"
CANDIDATE = "94107aedd9c68df9811c69c48b3ac0b7d2ec119f"
ROOT = Path(__file__).resolve().parents[4]
FOLDER = Path(__file__).resolve().parent


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(destination, *, scope=False):
    runtime = json.loads((FOLDER / "opposition-runtime.json").read_text())
    packages = sorted(
        [[d.metadata["Name"], d.version] for d in importlib.metadata.distributions()]
    )
    if (
        sys.version != runtime["python"]
        or packages != runtime["packages"]
        or Path(sys.executable).absolute() != Path(runtime["executable"]).absolute()
    ):
        raise RuntimeError("Comparison runtime differs from frozen environment")
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {
        "purpose": "Composite candidate qualification; no causal attribution to an individual change",
        "inference_performed": False,
        "model": "openrouter/nex-agi/nex-n2.5-pro:free",
        "trial_order": [
            ["baseline", "candidate"],
            ["candidate", "baseline"],
            ["baseline", "candidate"],
        ],
        "criteria": {
            "each_trial_accuracy_min": 0.75,
            "each_trial_contradiction_recall_min": 0.8,
            "paired_improvement": ["accuracy", "contradiction_recall"],
            "historical_false_contradictions": 0,
            "new_challenge_false_contradictions": 0,
        },
        "runtime_sha256": sha(FOLDER / "opposition-runtime.json"),
        "controls_sha256": sha(FOLDER / "historical-negative-controls.json"),
        "preparation_script_sha256": sha(Path(__file__)),
        "arms": {},
    }
    candidate = CANDIDATE
    if scope:
        candidate = "03ea84841983c93da170902c05b3fd846fb87360"
        manifest.update(
            series="opposition-scope-pro",
            scope_controls_sha256=sha(FOLDER / "partial-support-scope-controls.json"),
            scope_helper_sha256=sha(FOLDER / "scope_controls.py"),
        )
        manifest["criteria"]["all_candidate_scope_controls_both_modes"] = True
    for arm, revision in (("baseline", BASELINE), ("candidate", candidate)):
        snapshot = destination / arm
        snapshot.mkdir()
        sources = {}
        revisions = {"app": revision, "engine": revision, "evaluations": BASELINE}
        for subtree, pinned in revisions.items():
            with tempfile.TemporaryFile() as archive:
                subprocess.run(
                    ["git", "archive", pinned, subtree],
                    cwd=ROOT,
                    stdout=archive,
                    check=True,
                )
                archive.seek(0)
                with tarfile.open(fileobj=archive) as bundle:
                    bundle.extractall(snapshot, filter="data")
            entries = git("ls-tree", "-r", pinned, subtree).decode().splitlines()
            for entry in entries:
                metadata, relative = entry.split("\t", 1)
                mode, kind, expected = metadata.split()
                if kind != "blob":
                    raise RuntimeError(f"Unsupported source entry: {relative}")
                path = snapshot / relative
                content = (
                    os.readlink(path).encode()
                    if mode == "120000"
                    else path.read_bytes()
                )
                blob = hashlib.sha1(
                    b"blob " + str(len(content)).encode() + b"\0" + content
                ).hexdigest()
                if blob != expected:
                    raise RuntimeError(f"Snapshot mismatch: {relative}")
                sources[relative] = {
                    "git_blob": blob,
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
        manifest["arms"][arm] = {
            "snapshot": str(snapshot),
            "subtree_revisions": revisions,
            "subtree_trees": {
                name: git("rev-parse", f"{rev}:{name}").decode().strip()
                for name, rev in revisions.items()
            },
            "verified_sources": sources,
        }
    output = destination / "source-manifest.json"
    output.write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {
                "manifest": str(output),
                "inference_performed": False,
                "verified_files": {
                    arm: len(data["verified_sources"])
                    for arm, data in manifest["arms"].items()
                },
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--scope", action="store_true")
    args = parser.parse_args()
    prepare(args.destination.resolve(), scope=args.scope)
