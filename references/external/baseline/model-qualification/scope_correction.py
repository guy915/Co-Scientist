"""Auditable post-evaluation correction; never alter frozen trials or their gates."""

import argparse
import hashlib
import json
from pathlib import Path

from scope_controls import validate_scope_evidence


def corrected_scope_acceptance(record, dataset):
    from app.claims import as_passages

    # Preserve all structural and physical-evidence requirements. The return
    # value includes the known allowlist defect, so only its exceptions matter.
    validate_scope_evidence(record, dataset)
    accepted = True
    for panel in record["scope_controls"].values():
        accepted &= not panel["usage_evidence"]["recorded_deterministic_fallbacks"]
        for check, item in zip(panel["checks"], dataset["items"]):
            if check["verification_method"] != "lexical_founded":
                accepted &= check["passed"] is True
                continue
            texts = {p.evidence_id: p.text for p in as_passages(item["passages"])}
            quotes = check["quotes"]
            located = bool(quotes) and all(
                q["quote"]
                and type(q["start"]) is int
                and type(q["end"]) is int
                and 0 <= q["start"] < q["end"] <= len(texts.get(q["evidence_id"], ""))
                and texts[q["evidence_id"]][q["start"] : q["end"]] == q["quote"]
                for q in quotes
            )
            accepted &= bool(
                check["label"] == "contradicts"
                and check["label"] in item["allowed_labels"]
                and check["allowed_labels"] == item["allowed_labels"]
                and check["quotes_valid"] is True
                and located
                and check["nonempty_assessor_invocations"] > 0
            )
    return bool(accepted)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def receipt(folder, attempt=None, series="opposition-scope-pro"):
    if series not in {"opposition-scope-pro", "opposition-magnitude-pro"}:
        raise ValueError("Unknown correction series")
    if attempt and series != "opposition-scope-pro":
        raise ValueError("Recovery is only recorded for the scope series")
    suffix = f"-{attempt}" if attempt else ""
    summary_path = folder / f"{series}-paired-summary{suffix}.json"
    summary = json.loads(summary_path.read_text())
    if summary.get("attempt") != attempt:
        raise ValueError("Attempt metadata mismatch")
    dataset_path = folder / "partial-support-scope-controls.json"
    dataset = json.loads(dataset_path.read_text())
    preflight = (
        "scope-preflight.json"
        if series == "opposition-scope-pro"
        else "magnitude-preflight.json"
    )
    frozen = json.loads((folder / preflight).read_text())["source_manifest"]
    helper_path = folder / "scope_controls.py"
    if (
        digest(helper_path) != frozen["scope_helper_sha256"]
        or digest(dataset_path) != frozen["scope_controls_sha256"]
    ):
        raise ValueError("Frozen helper or dataset changed")
    pairs = []
    for pair in summary["pairs"]:
        for artifact in pair["artifacts"]:
            if digest(folder / artifact["path"]) != artifact["sha256"]:
                raise ValueError("Raw artifact changed")
        candidate = json.loads((folder / pair["artifacts"][1]["path"]).read_text())
        corrected = corrected_scope_acceptance(candidate, dataset)
        criteria = dict(pair["criteria"])
        criteria["candidate_scope_controls"] = corrected
        corrected_pair = {
            "trial": pair["trial"],
            "criteria": criteria,
            "passed": all(criteria.values()),
            "original_scope_checks": {
                m: p["checks"] for m, p in candidate["scope_controls"].items()
            },
        }
        if "recovery_of" in pair:
            corrected_pair["recovery_of"] = pair["recovery_of"]
        pairs.append(corrected_pair)
    result = {
        "series": series,
        "purpose": "Correct the lexical_founded provenance false rejection only; no inference or changed scientific observations",
        "semantic_delta": "A primary model contradiction retained by a located-quote/subject/negation guard is not deterministic fallback",
        "correction_sha256": digest(Path(__file__)),
        "frozen_helper_sha256": digest(helper_path),
        "dataset_sha256": digest(dataset_path),
        "original_summary_sha256": digest(summary_path),
        "original_summary": summary,
        "pairs": pairs,
        "complete": summary["complete"],
        "corrected_acceptance": summary["complete"]
        and len(pairs) == 3
        and all(p["passed"] for p in pairs),
    }
    if attempt:
        result["attempt"] = attempt
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--series",
        choices=["opposition-scope-pro", "opposition-magnitude-pro"],
        default="opposition-scope-pro",
    )
    parser.add_argument("--attempt", choices=["recovery1"])
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent
    result = receipt(folder, attempt=args.attempt, series=args.series)
    suffix = f"-{args.attempt}" if args.attempt else ""
    (folder / f"{args.series}-corrected-summary{suffix}.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "complete": result["complete"],
                "corrected_acceptance": result["corrected_acceptance"],
                "pairs": len(result["pairs"]),
            }
        )
    )
