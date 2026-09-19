"""Citation/claim-entailment evaluation.

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

import json
import pathlib
import sys
from collections import defaultdict
from typing import Any

from evaluations._artifacts import write_dated_artifact

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_DATASET = _ROOT / "evaluations" / "datasets" / "citation_entailment_v1.json"
_CHALLENGE_DATASET = (
    _ROOT / "evaluations" / "datasets" / "citation_entailment_challenge_v1.json"
)

# Documented production gates for the semantic (LLM/NLI) assessor on the
# adversarial challenge panel. Contradiction recall is the safety-critical
# metric: an unsupported claim reaching a categorical proposal is the failure
# the publication gate exists to stop, so a missed contradiction is the most
# dangerous error. Overall accuracy and abstention are reported and gated more
# loosely because conservative abstention (predicting insufficient on a genuine
# support) is safe, merely costing recall. These thresholds are the replica's
# own reconstructed gates, not Google's undisclosed production thresholds.
_PRODUCTION_GATES = {
    "contradiction_recall": 0.80,
    "accuracy": 0.75,
}

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


def _gate_report(metrics: dict[str, Any]) -> dict[str, Any]:
    """Return a per-gate pass/fail report against the production thresholds."""
    checks = {
        name: {
            "value": metrics[name],
            "threshold": threshold,
            "passed": metrics[name] >= threshold,
        }
        for name, threshold in _PRODUCTION_GATES.items()
    }
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
    }


def run(
    *,
    use_llm: bool = False,
    dataset_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Evaluate the assessor over the dataset and return the metrics report.

    The default uses the offline deterministic assessor for CI. ``use_llm``
    selects the semantic assessor after explicit campaign configuration.
    ``dataset_path`` selects the small v1 or adversarial challenge panel.
    """
    assessor, assessor_id = _selected_assessor(use_llm)
    dataset = _load_dataset(dataset_path or _DATASET)
    from evaluations._panel_identity import capture_panel

    with capture_panel(
        "citation_entailment",
        dataset,
        assessor_id.removeprefix("llm:"),
        live=use_llm,
    ) as evidence:
        rows = _predict(dataset["items"], assessor, assessor_id)
    matrix = _confusion(rows)
    metrics = _metrics(matrix)
    metrics["by_kind"] = _accuracy_by_kind(rows)
    return {
        **evidence,
        "dataset": dataset["name"],
        "dataset_version": dataset["version"],
        "assessor": assessor_id,
        "metrics": metrics,
        "confusion": matrix,
        "production_gates": _gate_report(metrics),
        "external_gap": (
            "Human-audited representative sample and threshold calibration not "
            "performed (no annotator panel); synthetic dataset only. "
            "Retraction handling is upstream of this assessor (retracted "
            "sources are "
            "quarantined before grounding), so a retracted-passage item scored "
            "here isolates only the assessor, not the full pipeline."
        ),
    }


def _selected_assessor(use_llm: bool) -> tuple[Any, str]:
    if use_llm:
        return _build_llm_assessor()
    from app.claims import deterministic_assessor

    return deterministic_assessor, "deterministic-v1"


def _build_llm_assessor() -> tuple[Any, str]:
    """Build the LLM assessor from the MODEL_NAME env (for --llm runs)."""
    from evaluations._live_config import configure_live_environment

    model = configure_live_environment()
    from app.claim_verifier import make_llm_assessor

    assessor, assessor_id = make_llm_assessor(model)
    return assessor, str(assessor_id)


def _run_selected_assessor(
    dataset_path: pathlib.Path,
) -> tuple[dict[str, Any], str]:
    """Run the eval with the ``--llm``-selected assessor -> (report, tag)."""
    if "--llm" in sys.argv[1:]:
        report = run(use_llm=True, dataset_path=dataset_path)
        assessor_id = str(report["assessor"])
        return report, assessor_id.replace("/", "_").replace(":", "_")
    return run(dataset_path=dataset_path), "deterministic"


def _write_artifact(
    report: dict[str, Any], panel: str, challenge: bool, tag: str
) -> pathlib.Path:
    """Write the dated result artifact and return its path."""
    suffix = f"-{panel}" if challenge else ""
    return write_dated_artifact(report, f"citation-entailment{suffix}-{tag}")


def main() -> int:
    """Run the eval, write a dated artifact, and print a summary.

    ``--llm`` scores the real LLM assessor (needs a provider key); the default
    scores the offline deterministic assessor. ``--challenge`` selects the
    larger adversarial panel and enforces the documented production gates
    (returning a non-zero exit if a gate fails).
    """
    challenge = "--challenge" in sys.argv[1:]
    dataset_path = _CHALLENGE_DATASET if challenge else _DATASET
    panel = "challenge" if challenge else "v1"

    report, tag = _run_selected_assessor(dataset_path)
    out = _write_artifact(report, panel, challenge, tag)

    m = report["metrics"]
    print(
        f"citation-entailment eval [{report['assessor']}] panel={panel}: "
        f"n={m['n']} accuracy={m['accuracy']} "
        f"contradiction_recall={m['contradiction_recall']}"
    )
    print(f"by kind: {m['by_kind']}")
    gates = report["production_gates"]
    print(f"production gates passed: {gates['passed']} ({gates['checks']})")
    print(f"wrote {out}")
    # On the challenge panel the documented gates are enforced; the offline
    # deterministic assessor is expected to fail them (it is a lexical baseline,
    # not the production semantic path), so only gate the run when scoring the
    # real assessor.
    if challenge and "--llm" in sys.argv[1:] and not gates["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
