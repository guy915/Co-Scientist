"""Run credential-free evaluator compatibility checks on prepared snapshots."""

import os
import sys
import json
import subprocess
import hashlib
import importlib.metadata
from pathlib import Path

root = Path(__file__).resolve().parents[4]
manifest_path = Path(sys.argv[1]).resolve()
manifest = json.loads(manifest_path.read_text())
code = """import sys,json,hashlib
from pathlib import Path
from evaluations import citation_eval
report=citation_eval.run(use_llm=False,dataset_path=citation_eval._CHALLENGE_DATASET)
root=Path.cwd().resolve()
sources={}
for name,module in list(sys.modules.items()):
 if name.split('.')[0] not in {'app','co_scientist','evaluations'}: continue
 filename=getattr(module,'__file__',None)
 if filename is None: continue
 path=Path(filename).resolve()
 if not path.is_relative_to(root): raise RuntimeError('Escaped import: '+name)
 sources[name]={'path':str(path.relative_to(root)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
print(json.dumps({'mode':'offline','report':report,'imports':sources}))
"""
if manifest.get("series") in {"opposition-scope-pro", "opposition-magnitude-pro"}:
    code = code.replace(
        "root=Path.cwd().resolve()",
        """from app import claim_verifier, claim_verifier_batch
from app.claims import AssessorDraft, EntailmentLabel
from scope_controls import evaluate_model_scope_controls
# Exercise both snapshot APIs without calling a provider. These intentionally
# inconclusive drafts are compatibility evidence, never scientific acceptance.
claim_verifier.make_llm_assessor=lambda model: (lambda claim, passages: AssessorDraft(EntailmentLabel.INSUFFICIENT), 'offline')
claim_verifier_batch.make_llm_batch_assessor=lambda model: (lambda claims, passages: [AssessorDraft(EntailmentLabel.INSUFFICIENT) for _ in claims], 'offline')
controls=json.loads(Path(sys.argv[1]).read_text())
scope_results=evaluate_model_scope_controls(controls, 'openrouter/nex-agi/nex-n2.5-pro:free')
assert set(scope_results)=={'single','batch_single_claim'}
assert all(len(p['checks'])==len(controls['items']) for p in scope_results.values())
assert all(not p['usage_evidence']['physical_calls'] for p in scope_results.values())
assert all(c['nonempty_assessor_invocations'] > 0 for p in scope_results.values() for c in p['checks'])
root=Path.cwd().resolve()""",
    )
results = {}
for arm, data in manifest["arms"].items():
    snapshot = Path(data["snapshot"])
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": f"{snapshot}:{snapshot}/app:{snapshot}/engine/src:{Path(__file__).parent}",
        "PYTHON_DOTENV_DISABLED": "1",
        "COSCIENTIST_CACHE_ENABLED": "0",
    }
    result = subprocess.run(
        [
            str(root / ".venv/bin/python"),
            "-c",
            code,
            str(Path(__file__).with_name("partial-support-scope-controls.json")),
        ],
        cwd=snapshot,
        env=env,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        print(result.stderr[-3000:])
        sys.exit(result.returncode)
    output = json.loads(result.stdout)
    for name, source in output["imports"].items():
        if data["verified_sources"][source["path"]]["sha256"] != source["sha256"]:
            raise RuntimeError(f"Imported source mismatch: {name}")
    results[arm] = output
folder = root / "references/external/baseline/model-qualification"
artifact = {
    "purpose": "Offline composite-source compatibility preflight; not live scientific acceptance",
    "inference_performed": False,
    "preflight_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "runtime": {
        "executable": sys.executable,
        "python": sys.version,
        "packages": sorted(
            [
                [d.metadata["Name"], d.version]
                for d in importlib.metadata.distributions()
            ]
        ),
    },
    "environment_policy": {
        "inherited": ["PATH"],
        "PYTHON_DOTENV_DISABLED": "1",
        "COSCIENTIST_CACHE_ENABLED": "0",
        "PYTHONPATH": "<snapshot>:<snapshot>/app:<snapshot>/engine/src:<qualification-helper-dir>",
        "credentials": "none",
    },
    "source_manifest": manifest,
    "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    "subtree_revisions": {
        a: d["subtree_revisions"] for a, d in manifest["arms"].items()
    },
    "arms": results,
}
(
    folder
    / (
        "magnitude-preflight.json"
        if manifest.get("series") == "opposition-magnitude-pro"
        else "scope-preflight.json"
        if manifest.get("series") == "opposition-scope-pro"
        else "retrieval-preflight.json"
    )
).write_text(json.dumps(artifact, indent=2) + "\n")
print(
    json.dumps(
        {
            arm: {"verified_imports": len(data["imports"]), "mode": data["mode"]}
            for arm, data in results.items()
        }
    )
)
