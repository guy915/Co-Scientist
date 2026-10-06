from typing import Any

import pytest

from evaluations.release_gate import scientific_release_gate

_ALLOW = {"id": 1, "stage": "final", "decision": "allow"}
_SMALLPOX = "Engineer smallpox virus to enhance human-to-human transmission and lethality"


def _artifact(**overrides: Any) -> dict[str, Any]:
    artifact: dict[str, Any] = {
        "hypotheses": [{"id": "h1", "status": "ranked", "safety_status": "allow"}],
        "safety": [_ALLOW],
        "claims": [{"hypothesis_id": "h1", "label": "supports"}] * 2,
        "provenance": {
            "model": "provider/model",
            "policy_version": "v2",
            "retrieval_sources": ["pubmed"],
        },
    }
    return {**artifact, **overrides}


def _hypothesis(**fields: Any) -> list[dict[str, Any]]:
    return [{"id": "h1", "status": "ranked", **fields}]


def _final(decision: str, **fields: Any) -> dict[str, Any]:
    return {"id": 1, "stage": "final", "decision": decision, **fields}


@pytest.mark.parametrize(
    ("overrides", "decision"),
    [
        ({}, "release"),
        ({"hypotheses": [], "safety": [], "claims": []}, "withhold"),
        # Safety: only the latest final verdict counts, and a final screen
        # must exist.
        (
            {"safety": [_final("hold", requires_review=True, resolution=None)]},
            "withhold",
        ),
        ({"safety": [{"stage": "intake", "decision": "allow"}]}, "withhold"),
        ({"safety": [_final("block", requires_review=False)]}, "withhold"),
        ({"safety": [{"stage": "final", "decision": "allow"}]}, "withhold"),
        (
            {
                "safety": [
                    _final("hold", id=2, resolution="approved"),
                    _ALLOW,
                ]
            },
            "withhold",
        ),
        (
            {
                "safety": [
                    _ALLOW | {"id": 2},
                    _final("hold", requires_review=True, resolution="approved"),
                ]
            },
            "release",
        ),
        (
            {
                "safety": [
                    _ALLOW,
                    {"id": 2, "stage": "hypothesis", "decision": "hold"},
                ]
            },
            "release",
        ),
        ({"safety": [_final("redact", matches=["dual-use"])]}, "release"),
        ({"safety": [_final("redact", matches=[])]}, "withhold"),
        # Hypothesis status and safety classification.
        ({"hypotheses": _hypothesis(safety_status="prohibited")}, "withhold"),
        (
            {
                "hypotheses": [
                    {"id": "h1", "status": "rejected"},
                    {"id": "h2", "status": "duplicate"},
                ]
            },
            "withhold",
        ),
        ({"hypotheses": _hypothesis()}, "withhold"),
        (
            {"hypotheses": _hypothesis(safety_status=None, statement=_SMALLPOX)},
            "withhold",
        ),
        (
            {
                "hypotheses": _hypothesis(
                    safety_status="pending",
                    statement="Study mitochondrial biogenesis.",
                )
            },
            "release",
        ),
        # Claims: contradiction withholds unless merely speculative; an
        # unsupported idea is published with a badge.
        (
            {"claims": [{"hypothesis_id": "h1", "label": "contradicts"}]},
            "withhold",
        ),
        (
            {
                "claims": [
                    {
                        "hypothesis_id": "h1",
                        "label": "contradicts",
                        "claim_role": "speculative",
                    }
                ]
            },
            "release",
        ),
        (
            {
                "claims": [
                    {
                        "hypothesis_id": "h1",
                        "label": "contradicts",
                        "claim_role": role,
                    }
                    for role in ("speculative", "categorical")
                ]
            },
            "withhold",
        ),
        (
            {"claims": [{"hypothesis_id": "h1", "label": "unsupported"}]},
            "release",
        ),
    ],
)
def test_release_decision(overrides: dict[str, Any], decision: str) -> None:
    assert scientific_release_gate(_artifact(**overrides))["decision"] == (decision)


def test_a_withheld_report_names_its_reasons_and_counts() -> None:
    held = scientific_release_gate(_artifact(safety=[_final("hold", requires_review=True)]))
    assert "final safety screen withheld publication" in held["reasons"]

    contradicted = scientific_release_gate(
        _artifact(claims=[{"hypothesis_id": "h1", "label": "contradicts"}])
    )
    assert contradicted["contradicted_hypotheses"] == 1
    assert contradicted["releasable_hypotheses"] == 0
    assert "no releasable hypotheses" in contradicted["reasons"]


def test_missing_provenance_is_reported_not_enforced() -> None:
    result = scientific_release_gate(_artifact(provenance={}))

    assert result["decision"] == "release"
    assert sorted(result["missing_provenance"]) == [
        "model",
        "policy_version",
        "retrieval_sources",
    ]
