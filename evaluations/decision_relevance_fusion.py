import argparse
import hashlib
import json
import random
import statistics
from pathlib import Path
from typing import Any

from co_scientist.platform.llm.decisions.calibration import LabeledDecision, choose_threshold
from co_scientist.platform.retrieval.evidence.relevance import combine_hybrid_score
from co_scientist.platform.retrieval.evidence.search_fusion import merge_search_results

from evaluations.decision_bakeoff import agrees


def _measure_inputs(
    rows: list[dict[str, Any]], threshold: float | None, *, cascade: bool
) -> dict[str, Any]:
    measurements: list[dict[str, float]] = []
    accepted = 0
    for row in rows:
        if "reference" not in row:
            continue
        names = list(row["reference"])
        if not names:
            raise ValueError("reference batch is empty")
        take_decision = "decision" in row and (
            not cascade or (threshold is not None and row["confidence"] >= threshold)
        )
        accepted += int(take_decision)
        semantic = row["decision"] if take_decision else row["reference"]
        # Repeated source orders stress selection; they are not independent labels.
        for scenario in range(32):
            seed = int(hashlib.sha256(f"{row['id']}:{scenario}".encode()).hexdigest(), 16)
            rng = random.Random(seed)
            sources = []
            for source in ("pubmed", "openalex"):
                ordered = list(names)
                rng.shuffle(ordered)
                sources.append(
                    (source, {name: {"title": name, "source": source} for name in ordered})
                )
            lexical, _ = merge_search_results(sources, deduplicate=False)
            reference_scores = {
                name: combine_hybrid_score(item["retrieval_score"], row["reference"][name])
                for name, item in lexical.items()
            }
            decision_scores = {
                name: combine_hybrid_score(item["retrieval_score"], semantic[name])
                for name, item in lexical.items()
            }
            original = sorted(lexical, key=lambda name: -reference_scores[name])
            actual = sorted(lexical, key=lambda name: -decision_scores[name])
            result = {
                "top1_exact": float(original[0] == actual[0]),
                "complete_order_exact": float(original == actual),
            }
            for k in (3, 5):
                size = min(k, len(names))
                result[f"top{k}_overlap"] = len(set(original[:size]) & set(actual[:size])) / size
            position = {name: index for index, name in enumerate(actual)}
            comparisons = [
                position[a] < position[b]
                for index, a in enumerate(original)
                for b in original[index + 1 :]
                if reference_scores[a] != reference_scores[b]
            ]
            result["non_tied_pair_order_agreement"] = (
                float(statistics.mean(comparisons)) if comparisons else 1.0
            )
            measurements.append(result)
    return {
        "reference_batches": sum("reference" in row for row in rows),
        "decision_batches_used": accepted,
        "generated_scenarios": len(measurements),
        "metrics": {
            name: statistics.mean(row[name] for row in measurements) for name in measurements[0]
        }
        if measurements
        else {},
    }


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = report["rows"]
    served = [row for row in rows if "decision" in row]
    if any(row.get("decision_representation") != "per-candidate-question/v1" for row in served):
        raise ValueError("representation mismatch")
    calibration = []
    last_calibration = -1
    for index, row in enumerate(rows):
        if "decision" not in row:
            continue
        for name, value in row["decision"].items():
            calibration.append(
                LabeledDecision(
                    row["answers"][name]["confidence"],
                    agrees("literature_relevance", {name: row["reference"][name]}, {name: value}),
                )
            )
        last_calibration = index
        if len(calibration) >= 100:
            break
    threshold = choose_threshold(calibration)
    held_out = rows[last_calibration + 1 :] if len(calibration) >= 100 else []
    return {
        "basis": (
            "Generated two-source RRF inputs on identical semantic judgments; "
            "no historical lexical replay."
        ),
        "limitation": (
            "32 deterministic source orders per batch are stress scenarios, not new labels. "
            "Score-based selection has no source-slot reservations."
        ),
        "representation": "per-candidate-question/v1",
        "calibration_labels": len(calibration),
        "threshold": threshold,
        "adoption_ready": False,
        "raw_served": _measure_inputs(served, threshold, cascade=False),
        "held_out_cascade": _measure_inputs(held_out, threshold, cascade=True),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = validate_report(json.loads(args.report.read_text()))
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
