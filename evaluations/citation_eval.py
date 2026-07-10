"""Citation/claim-entailment evaluation (PLAN.md Milestone 5).

Runs the claim-level entailment assessor (``app.claims.assess_claim``) over a
labeled dataset and reports precision/recall per label, contradiction recall,
abstention rate, and overall accuracy — the metrics M5 requires before
selecting thresholds. The dataset here is small and synthetic (legally
shareable); a human-audited representative sample and threshold calibration
remain an external gap and are recorded as such.

Run: ``python -m evaluations.citation_eval`` (writes a dated result artifact
under ``evaluations/results/`` and prints a summary).
"""

from __future__ import annotations

import datetime
import json
import pathlib
import sys
from collections import defaultdict
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_DATASET = _ROOT / "evaluations" / "datasets" / "citation_entailment_v1.json"
_RESULTS_DIR = _ROOT / "evaluations" / "results"

# The app package lives under app/; make it importable for the assessor.
sys.path.insert(0, str(_ROOT / "app"))


def _load_dataset(path: pathlib.Path) -> dict[str, Any]:
    dataset: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return dataset


def _confusion(items: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Return a nested expected->predicted count matrix over the dataset."""
    from app.claims import assess_claim  # imported here so path is set first

    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for item in items:
        predicted = assess_claim(item["claim"], item["passages"]).label.value
        matrix[item["label"]][predicted] += 1
    return {k: dict(v) for k, v in matrix.items()}


def _metrics(matrix: dict[str, dict[str, int]]) -> dict[str, Any]:
    """Compute per-label precision/recall and overall accuracy."""
    labels = {"supports", "contradicts", "insufficient"}
    total = sum(sum(row.values()) for row in matrix.values())
    correct = sum(matrix.get(lbl, {}).get(lbl, 0) for lbl in labels)

    per_label: dict[str, dict[str, float]] = {}
    for lbl in labels:
        tp = matrix.get(lbl, {}).get(lbl, 0)
        predicted_lbl = sum(matrix.get(exp, {}).get(lbl, 0) for exp in matrix)
        actual_lbl = sum(matrix.get(lbl, {}).values())
        precision = tp / predicted_lbl if predicted_lbl else 0.0
        recall = tp / actual_lbl if actual_lbl else 0.0
        per_label[lbl] = {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
        }

    return {
        "accuracy": round(correct / total, 3) if total else 0.0,
        "contradiction_recall": per_label["contradicts"]["recall"],
        "abstention_rate": round(
            sum(matrix.get(exp, {}).get("insufficient", 0) for exp in matrix)
            / total,
            3,
        )
        if total
        else 0.0,
        "per_label": per_label,
        "n": total,
    }


def run() -> dict[str, Any]:
    """Evaluate the assessor over the dataset and return the metrics report."""
    dataset = _load_dataset(_DATASET)
    matrix = _confusion(dataset["items"])
    metrics = _metrics(matrix)
    return {
        "dataset": dataset["name"],
        "dataset_version": dataset["version"],
        "assessor": "deterministic-v1",
        "metrics": metrics,
        "confusion": matrix,
        "external_gap": (
            "Human-audited representative sample and threshold calibration not "
            "performed (no annotator panel); synthetic dataset only."
        ),
    }


def main() -> int:
    """Run the eval, write a dated artifact, and print a summary."""
    report = run()
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.date.today().isoformat()
    out = _RESULTS_DIR / f"citation-entailment-{date}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    m = report["metrics"]
    print(
        f"citation-entailment eval: n={m['n']} accuracy={m['accuracy']} "
        f"contradiction_recall={m['contradiction_recall']}"
    )
    print(f"wrote {out.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
