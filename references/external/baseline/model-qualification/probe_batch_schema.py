"""Invoke the frozen four-claim batch-schema panel once."""

import datetime
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from evaluations._live_config import configure_live_environment

MODEL = configure_live_environment()

from app.claim_verifier_batch import _BATCH_DRAFT_SCHEMA, make_llm_batch_assessor  # noqa: E402
from app.claims import EvidencePassage, assess_claims_batch  # noqa: E402
from evaluations._panel_identity import capture_panel  # noqa: E402
from co_scientist.llm_free_catalog import current_catalog, verify_model  # noqa: E402
import probe_citation_panel as observer  # noqa: E402


FOLDER = Path(__file__).resolve().parent
PREFLIGHT = FOLDER / "batch-schema-preflight109.json"
ROOT = Path(
    subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], cwd=FOLDER, text=True
    ).strip()
)
ASSESSOR_MODULES = (
    "app.claim_verifier_batch",
    "app.claims_batch",
    "app.claim_verifier",
    "app.claim_verifier_opposition",
    "app.claims_assessor",
    "app.claims_span",
    "app.claims_gate",
    "co_scientist.llm",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_to_root(path: Path) -> Path:
    for parent in path.parents:
        if parent.samefile(ROOT):
            return path.relative_to(parent)
    raise RuntimeError(f"assessor import escaped repository: {path}")


def assessor_source_hashes() -> dict:
    """Record the concrete production assessor modules this probe imports."""
    sources = {}
    for name in ASSESSOR_MODULES:
        path = Path(importlib.import_module(name).__file__).resolve()
        relative = relative_to_root(path)
        sources[name] = {"path": str(relative), "sha256": digest(path)}
    return sources


def head_revision() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def load_frozen_panel() -> tuple[dict, dict]:
    """Load exactly the manifest-selected claims after input/schema checks."""
    preflight = json.loads(PREFLIGHT.read_text())
    dataset_path = FOLDER / preflight["source_dataset"]
    if digest(dataset_path) != preflight["source_sha256"]:
        raise ValueError("Frozen batch dataset differs from preflight")
    if hashlib.sha256(json.dumps(_BATCH_DRAFT_SCHEMA, sort_keys=True).encode()).hexdigest() != preflight["schema_sha256"]:
        raise ValueError("Batch assessor schema differs from preflight")
    source = json.loads(dataset_path.read_text())
    by_id = {item["id"]: item for item in source["items"]}
    selected = [by_id[item_id] for item_id in preflight["selected_ids"]]
    if len(by_id) != len(source["items"]) or len(selected) != 4:
        raise ValueError("Frozen batch panel ids are invalid")
    if [item["allowed_labels"] for item in selected] != [
        [label] for label in preflight["expected_labels"]
    ]:
        raise ValueError("Frozen batch panel labels differ from preflight")
    return {"items": selected}, preflight


def run_batch(dataset: dict, batch_assessor, assessor_id: str) -> dict:
    """Use the production batch boundary with all selected claims together."""
    items = dataset["items"]
    claims = [item["claim"] for item in items]
    passages = [
        EvidencePassage(
            evidence_id=item["id"], text=item["passages"][0], source="frozen_control"
        )
        for item in items
    ]
    assessments = assess_claims_batch(
        claims, passages, batch_assessor=batch_assessor, assessor_id=assessor_id
    )
    return {
        "checks": [
            {
                "id": item["id"],
                "label": assessment.label.value,
                "verification_method": assessment.verification_method,
                "supporting_spans": [span.to_dict() for span in assessment.supporting_passages],
                "contradicting_spans": [
                    span.to_dict() for span in assessment.contradicting_passages
                ],
            }
            for item, assessment in zip(items, assessments)
        ]
    }


def main() -> int:
    output = Path(os.environ["QUALIFICATION_OUTPUT"])
    record = {
        "trial": int(os.environ["QUALIFICATION_TRIAL"]),
        "source_commit": os.environ["QUALIFICATION_REVISION"],
        "requested_model": MODEL,
        "probe_sha256": digest(Path(__file__)),
        "preflight_sha256": digest(PREFLIGHT),
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "batch_invocations": [],
    }
    with output.open("x") as artifact:
        try:
            dataset, preflight = load_frozen_panel()
            record["frozen_inputs"] = {
                "dataset": preflight["source_dataset"],
                "dataset_sha256": preflight["source_sha256"],
                "schema_sha256": preflight["schema_sha256"],
                "selected_ids": preflight["selected_ids"],
                "expected_labels": preflight["expected_labels"],
            }
            if record["source_commit"] != head_revision():
                raise ValueError("QUALIFICATION_REVISION differs from git HEAD")
            record["assessor_sources"] = assessor_source_hashes()
            catalog = current_catalog()
            raw_model = MODEL.removeprefix("openrouter/")
            verify_model(raw_model, catalog)
            record["eligibility"] = catalog[raw_model]
            observer._REQUESTS.clear()
            observer.litellm.acompletion = observer.observed_transport
            assessor, assessor_id = make_llm_batch_assessor(MODEL)

            def observed_assessor(claims, passages):
                record["batch_invocations"].append(
                    {"claims": len(claims), "passages": len(passages)}
                )
                return assessor(claims, passages)

            with capture_panel("citation_entailment", dataset, MODEL, live=True) as evidence:
                record["panel_evidence"] = evidence
                record["report"] = run_batch(dataset, observed_assessor, assessor_id)
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            record["error"] = re.sub(
                r"user_[A-Za-z0-9]+", "[redacted-account]", str(exc)
            ).replace(os.getenv("OPENROUTER_API_KEY", ""), "[redacted]")[:2000]
        finally:
            record["physical_requests"] = observer._REQUESTS
            record["physical_request_count"] = len(observer._REQUESTS)
            record["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            artifact.write(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"trial": record["trial"], "error_type": record.get("error_type")}))
    return 1 if "error_type" in record else 0


if __name__ == "__main__":
    sys.exit(main())
