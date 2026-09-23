"""Correct only the evidenced provenance false rejection, never missing evidence."""

from copy import deepcopy
import json

import pytest

from scope_correction import corrected_scope_acceptance
from test_scope_controls import scope_record, DATASET


def contradiction_record():
    dataset = deepcopy(DATASET)
    item = dataset["items"][0]
    item["claim"] = "Treatment reduces cell growth."
    item["passages"] = ["Treatment did not reduce cell growth."]
    item["allowed_labels"] = ["contradicts"]
    from app.claims import as_passages

    passage = as_passages(item["passages"])[0]
    record = scope_record()
    for panel in record["scope_controls"].values():
        check = panel["checks"][0]
        check.update(
            label="contradicts",
            allowed_labels=["contradicts"],
            verification_method="lexical_founded",
            passed=False,
            quotes=[
                {
                    "evidence_id": passage.evidence_id,
                    "quote": passage.text,
                    "start": 0,
                    "end": len(passage.text),
                }
            ],
        )
    return record, dataset


def test_corrects_guarded_model_contradiction_without_mutating_raw_record():
    record, dataset = contradiction_record()
    original = deepcopy(record)
    assert corrected_scope_acceptance(record, dataset)
    assert record == original


@pytest.mark.parametrize(
    "method", ["deterministic_lexical", "legacy_unknown", "invented"]
)
def test_does_not_accept_fallback_or_unknown_provenance(method):
    record, dataset = contradiction_record()
    record["scope_controls"]["single"]["checks"][0]["verification_method"] = method
    assert not corrected_scope_acceptance(record, dataset)


def test_quote_flag_alone_cannot_establish_located_quote():
    record, dataset = contradiction_record()
    record["scope_controls"]["single"]["checks"][0]["quotes"][0]["quote"] = "invented"
    assert not corrected_scope_acceptance(record, dataset)


def test_retains_no_fallback_gate():
    record, dataset = contradiction_record()
    record["scope_controls"]["single"]["usage_evidence"][
        "recorded_deterministic_fallbacks"
    ] = {"fallback": 1}
    assert not corrected_scope_acceptance(record, dataset)


def test_requires_physical_usage_even_for_correct_labels():
    record, dataset = contradiction_record()
    record["physical_requests"] = []
    with pytest.raises(ValueError, match="physical"):
        corrected_scope_acceptance(record, dataset)


def receipt_files(folder, *, series="opposition-scope-pro"):
    import hashlib
    import json
    from pathlib import Path
    import scope_controls

    record, dataset = contradiction_record()
    files = {
        "baseline.json": {},
        "candidate.json": record,
        "partial-support-scope-controls.json": dataset,
    }
    for name, data in files.items():
        (folder / name).write_text(json.dumps(data))
    helper = Path(scope_controls.__file__).read_bytes()
    (folder / "scope_controls.py").write_bytes(helper)

    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    preflight = (
        "magnitude-preflight.json"
        if series == "opposition-magnitude-pro"
        else "scope-preflight.json"
    )
    (folder / preflight).write_text(
        json.dumps(
            {
                "source_manifest": {
                    "scope_helper_sha256": sha(folder / "scope_controls.py"),
                    "scope_controls_sha256": sha(
                        folder / "partial-support-scope-controls.json"
                    ),
                }
            }
        )
    )
    summary = {
        "complete": False,
        "accepted": False,
        "pairs": [
            {
                "trial": 1,
                "passed": False,
                "criteria": {"candidate_scope_controls": False, "other_gate": False},
                "artifacts": [
                    {"path": name, "sha256": sha(folder / name)}
                    for name in ("baseline.json", "candidate.json")
                ],
            }
        ],
    }
    (folder / f"{series}-paired-summary.json").write_text(
        json.dumps(summary)
    )
    return summary


def test_receipt_preserves_original_and_every_other_gate(tmp_path):
    from scope_correction import receipt

    original = receipt_files(tmp_path)
    result = receipt(tmp_path)
    assert result["original_summary"] == original
    assert result["pairs"][0]["criteria"] == {
        "candidate_scope_controls": True,
        "other_gate": False,
    }
    assert not result["pairs"][0]["passed"]
    assert not result["corrected_acceptance"]


def test_receipt_rejects_changed_raw_artifact(tmp_path):
    from scope_correction import receipt

    receipt_files(tmp_path)
    with (tmp_path / "candidate.json").open("a") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="Raw artifact changed"):
        receipt(tmp_path)


def test_recovery_receipt_uses_its_own_summary_and_preserves_pair_provenance(
    tmp_path,
):
    from scope_correction import receipt

    original = receipt_files(tmp_path)
    recovery = deepcopy(original)
    recovery["attempt"] = "recovery1"
    recovery["pairs"][0]["recovery_of"] = [
        {"path": "candidate.json", "sha256": "original-candidate"}
    ]
    recovery_path = tmp_path / "opposition-scope-pro-paired-summary-recovery1.json"
    recovery_path.write_text(json.dumps(recovery))

    result = receipt(tmp_path, attempt="recovery1")

    assert result["attempt"] == "recovery1"
    assert result["original_summary"] == recovery
    assert result["pairs"][0]["recovery_of"] == recovery["pairs"][0]["recovery_of"]
    assert json.loads(
        (tmp_path / "opposition-scope-pro-paired-summary.json").read_text()
    ) == original


@pytest.mark.parametrize("recorded_attempt", [None, "other"])
def test_recovery_receipt_rejects_attempt_metadata_mismatch(tmp_path, recorded_attempt):
    from scope_correction import receipt

    recovery = receipt_files(tmp_path)
    if recorded_attempt is not None:
        recovery["attempt"] = recorded_attempt
    (tmp_path / "opposition-scope-pro-paired-summary-recovery1.json").write_text(
        json.dumps(recovery)
    )

    with pytest.raises(ValueError, match="Attempt metadata mismatch"):
        receipt(tmp_path, attempt="recovery1")


def test_original_receipt_rejects_attempt_metadata(tmp_path):
    from scope_correction import receipt

    original = receipt_files(tmp_path)
    original["attempt"] = "recovery1"
    (tmp_path / "opposition-scope-pro-paired-summary.json").write_text(
        json.dumps(original)
    )

    with pytest.raises(ValueError, match="Attempt metadata mismatch"):
        receipt(tmp_path)


def test_magnitude_receipt_uses_its_own_preflight_and_summary(tmp_path):
    from scope_correction import receipt

    original = receipt_files(tmp_path, series="opposition-magnitude-pro")
    result = receipt(tmp_path, series="opposition-magnitude-pro")

    assert result["series"] == "opposition-magnitude-pro"
    assert result["original_summary"] == original
    assert not (tmp_path / "opposition-scope-pro-corrected-summary.json").exists()
