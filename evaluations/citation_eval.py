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
import os
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


def _predict(
    items: list[dict[str, Any]],
    assessor: Any,
    assessor_id: str,
) -> list[tuple[str, str, str]]:
    """Assess each item once, returning (expected, predicted, kind) triples.

    Assessing once (rather than per metric) matters for the LLM assessor: each
    item costs one provider call.
    """
    from app.claims import as_passages, assess_claim

    rows: list[tuple[str, str, str]] = []
    for item in items:
        passages = as_passages(item["passages"])
        predicted = assess_claim(
            item["claim"],
            passages,
            assessor=assessor,
            assessor_id=assessor_id,
        ).label.value
        rows.append((item["label"], predicted, item.get("kind", "obvious")))
    return rows


def _confusion(rows: list[tuple[str, str, str]]) -> dict[str, dict[str, int]]:
    """Return a nested expected->predicted count matrix from prediction rows."""
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for expected, predicted, _kind in rows:
        matrix[expected][predicted] += 1
    return {k: dict(v) for k, v in matrix.items()}


def _accuracy_by_kind(
    rows: list[tuple[str, str, str]],
) -> dict[str, dict[str, Any]]:
    """Return per-kind accuracy, isolating where lexical vs semantic differ.

    The deterministic assessor is expected to score well on ``obvious``/
    ``mixed`` and poorly on ``hard_paraphrase`` (that is the gap the LLM/NLI
    assessor closes); reporting the split keeps that honest.
    """
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for expected, predicted, kind in rows:
        counts[kind][1] += 1
        if predicted == expected:
            counts[kind][0] += 1
    return {
        kind: {
            "accuracy": round(correct / total, 3) if total else 0.0,
            "n": total,
        }
        for kind, (correct, total) in sorted(counts.items())
    }


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


def run(
    *,
    assessor: Any = None,
    assessor_id: str = "deterministic-v1",
) -> dict[str, Any]:
    """Evaluate the assessor over the dataset and return the metrics report.

    The default (``assessor=None``) uses the offline deterministic assessor so
    the eval runs in CI. Pass a real assessor (e.g. the LLM assessor from
    ``app.claim_verifier.make_llm_assessor``) to score the semantic path; that
    requires a provider and is run out of band, not in the offline suite.
    """
    from app.claims import deterministic_assessor

    if assessor is None:
        assessor = deterministic_assessor
    dataset = _load_dataset(_DATASET)
    rows = _predict(dataset["items"], assessor, assessor_id)
    matrix = _confusion(rows)
    metrics = _metrics(matrix)
    metrics["by_kind"] = _accuracy_by_kind(rows)
    return {
        "dataset": dataset["name"],
        "dataset_version": dataset["version"],
        "assessor": assessor_id,
        "metrics": metrics,
        "confusion": matrix,
        "external_gap": (
            "Human-audited representative sample and threshold calibration not "
            "performed (no annotator panel); synthetic dataset only."
        ),
    }


def _build_llm_assessor() -> tuple[Any, str]:
    """Build the LLM assessor from the MODEL_NAME env (for --llm runs)."""
    from app.claim_verifier import make_llm_assessor

    model = os.getenv("MODEL_NAME") or "deepseek/deepseek-chat"
    assessor, assessor_id = make_llm_assessor(model)
    return assessor, str(assessor_id)


def main() -> int:
    """Run the eval, write a dated artifact, and print a summary.

    ``--llm`` scores the real LLM assessor (needs a provider key); the default
    scores the offline deterministic assessor.
    """
    if "--llm" in sys.argv[1:]:
        assessor, assessor_id = _build_llm_assessor()
        report = run(assessor=assessor, assessor_id=assessor_id)
        tag = assessor_id.replace("/", "_").replace(":", "_")
    else:
        report = run()
        tag = "deterministic"

    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.date.today().isoformat()
    out = _RESULTS_DIR / f"citation-entailment-{tag}-{date}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    m = report["metrics"]
    print(
        f"citation-entailment eval [{report['assessor']}]: n={m['n']} "
        f"accuracy={m['accuracy']} "
        f"contradiction_recall={m['contradiction_recall']}"
    )
    print(f"by kind: {m['by_kind']}")
    print(f"wrote {out.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
