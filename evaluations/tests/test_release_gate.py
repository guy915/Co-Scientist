"""Scientific release-gate tests."""

from evaluations.release_gate import scientific_release_gate


def _ready_artifact() -> dict[str, object]:
    return {
        "hypotheses": [{"id": "h1"}],
        "safety": [],
        "claims": [
            {"label": "supports"},
            {"label": "supports"},
        ],
        "provenance": {
            "model": "provider/model",
            "policy_version": "v2",
            "retrieval_sources": ["pubmed"],
        },
    }


def test_release_gate_releases_scientifically_ready_artifact() -> None:
    result = scientific_release_gate(_ready_artifact())
    assert result["decision"] == "release"
    assert result["reasons"] == []


def test_release_gate_withholds_unresolved_or_contradicted_artifact() -> None:
    artifact = _ready_artifact()
    artifact["safety"] = [{"requires_review": True, "resolution": None}]
    artifact["claims"] = [
        {"label": "supports"},
        {"label": "contradicts"},
    ]

    result = scientific_release_gate(artifact)

    assert result["decision"] == "withhold"
    assert "unresolved safety review" in result["reasons"]
    assert "contradicted scientific claim" in result["reasons"]
    assert any("verified claim ratio" in reason for reason in result["reasons"])
