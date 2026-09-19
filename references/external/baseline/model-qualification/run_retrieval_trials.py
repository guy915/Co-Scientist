"""Run the frozen, counterbalanced free-model comparison; never overwrite trials."""

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

from dotenv import dotenv_values

FOLDER = Path(__file__).resolve().parent
ROOT = FOLDER.parents[3]
manifest_path = Path(sys.argv[1]).resolve()
manifest = json.loads(manifest_path.read_text())
series = manifest.get("series", "opposition-retrieval-pro")
if series not in {"opposition-retrieval-pro", "opposition-scope-pro"}:
    raise RuntimeError("Unknown comparison series")
scope = series == "opposition-scope-pro"
preflight = json.loads(
    (
        FOLDER / ("scope-preflight.json" if scope else "retrieval-preflight.json")
    ).read_text()
)
if (
    hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    != preflight["source_manifest_sha256"]
):
    raise RuntimeError("Manifest differs from retained preflight")
if (
    hashlib.sha256(
        (FOLDER / "historical-negative-controls.json").read_bytes()
    ).hexdigest()
    != manifest["controls_sha256"]
):
    raise RuntimeError("Historical controls differ from frozen inputs")
runtime_path = FOLDER / "opposition-runtime.json"
runtime = json.loads(runtime_path.read_text())
if (
    sys.version != runtime["python"]
    or sys.executable != runtime["executable"]
    or sorted(
        [[d.metadata["Name"], d.version] for d in importlib.metadata.distributions()]
    )
    != runtime["packages"]
    or hashlib.sha256(runtime_path.read_bytes()).hexdigest()
    != manifest["runtime_sha256"]
):
    raise RuntimeError("Frozen runtime mismatch")
key = os.environ.get("OPENROUTER_API_KEY") or dotenv_values(ROOT / ".env").get(
    "OPENROUTER_API_KEY"
)
if not key:
    raise RuntimeError("OpenRouter credential unavailable")
if scope:
    for name, field in (
        ("partial-support-scope-controls.json", "scope_controls_sha256"),
        ("scope_controls.py", "scope_helper_sha256"),
    ):
        if hashlib.sha256((FOLDER / name).read_bytes()).hexdigest() != manifest[field]:
            raise RuntimeError("Scope observer or inputs changed")
model = manifest["model"]
# Freeze the exact execution observers before any inference.
identities = {
    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
    for p in (
        Path(__file__),
        FOLDER / "probe_citation_panel.py",
        FOLDER / "qualification_sources.py",
        FOLDER / "compare_opposition_panels.py",
        manifest_path,
    )
}
if scope:
    identities.update(
        {
            name: hashlib.sha256((FOLDER / name).read_bytes()).hexdigest()
            for name in ("scope_controls.py", "partial-support-scope-controls.json")
        }
    )
for trial, order in enumerate(manifest["trial_order"], 1):
    outputs = [FOLDER / f"{series}-{arm}-{trial}.json" for arm in order]
    logs = [manifest_path.parent / f"{arm}-{trial}.log" for arm in order]
    if any(path.exists() for path in outputs + logs):
        raise RuntimeError(
            "Existing trial artifacts: inspect and resume explicitly; never overwrite"
        )
    with urllib.request.urlopen(
        "https://openrouter.ai/api/v1/models", timeout=30
    ) as response:
        catalog = json.load(response)
    selected = next(
        (m for m in catalog["data"] if m["id"] == model.removeprefix("openrouter/")),
        None,
    )
    # Apply the same fail-closed admission contract as the pinned project.
    # A :free route may omit ancillary rates; any supplied paid rate rejects it.
    sys.path.insert(
        0, str(Path(manifest["arms"]["baseline"]["snapshot"]) / "engine/src")
    )
    from co_scientist.llm_free_catalog import verify_model

    verify_model(
        model.removeprefix("openrouter/"), {row["id"]: row for row in catalog["data"]}
    )
    catalog_path = FOLDER / f"{series}-catalog-{trial}.json"
    if catalog_path.exists():
        raise RuntimeError("Catalog record exists; inspect before resuming")
    catalog_path.write_text(
        json.dumps(
            {
                "selected": selected,
                "fetched_unix": time.time(),
                "catalog_sha256": hashlib.sha256(
                    json.dumps(catalog, sort_keys=True).encode()
                ).hexdigest(),
                "execution_sources": identities,
            },
            indent=2,
        )
        + "\n"
    )
    for arm, output in zip(order, outputs):
        data = manifest["arms"][arm]
        snapshot = Path(data["snapshot"])
        # Recheck all snapshot files, not just modules loaded by offline preflight.
        for relative, expected in data["verified_sources"].items():
            path = snapshot / relative
            content = (
                os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
            )
            if hashlib.sha256(content).hexdigest() != expected["sha256"]:
                raise RuntimeError(f"Snapshot changed: {relative}")
        env = {
            "PATH": os.environ["PATH"],
            "PYTHONPATH": f"{snapshot}:{snapshot}/engine/src:{snapshot}/app",
            "OPENROUTER_API_KEY": key,
            "MODEL_NAME": model,
            "PYTHON_DOTENV_DISABLED": "1",
            "COSCIENTIST_REQUIRE_FREE_MODELS": "1",
            "COSCIENTIST_CACHE_ENABLED": "0",
            "LITELLM_LOG": "ERROR",
            "QUALIFICATION_REVISION": data["subtree_revisions"]["app"],
            "QUALIFICATION_ROOT": str(snapshot),
            "QUALIFICATION_OUTPUT": str(output),
            "QUALIFICATION_TRIAL": str(trial),
            "QUALIFICATION_CONTROLS": str(FOLDER / "historical-negative-controls.json"),
            "QUALIFICATION_MANIFEST": str(manifest_path),
            "QUALIFICATION_ARM": arm,
        }
        if scope:
            env["QUALIFICATION_SCOPE_CONTROLS"] = str(
                FOLDER / "partial-support-scope-controls.json"
            )
        for name, expected in identities.items():
            path = manifest_path if name == manifest_path.name else FOLDER / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RuntimeError("Frozen execution script changed: " + name)
        time.sleep(4)
        print(f"Starting {arm} trial {trial}", flush=True)
        with (manifest_path.parent / f"{arm}-{trial}.log").open("x") as log:
            result = subprocess.run(
                [
                    str(ROOT / ".venv/bin/python"),
                    str(FOLDER / "probe_citation_panel.py"),
                ],
                cwd=snapshot,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        if result.returncode or not output.exists():
            raise RuntimeError(f"Child failed: {arm} {trial}, exit {result.returncode}")
        artifact = json.loads(output.read_text())
        print(
            json.dumps(
                {
                    "arm": arm,
                    "trial": trial,
                    "error_type": artifact.get("error_type"),
                    "metrics": artifact.get("report", {}).get("metrics"),
                    "requests": len(artifact.get("physical_requests", [])),
                }
            ),
            flush=True,
        )
        if artifact.get("error_type"):
            raise RuntimeError("Recorded live failure: stop batch and inspect")
