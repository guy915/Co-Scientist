"""Shared setup for outcome API and refinement contract tests."""

from __future__ import annotations

from typing import Any

from co_scientist.checkpoint import serialize_workflow_state
from co_scientist.models import Hypothesis

from app import auth, store

# Frozen public case from the external Robin outcome-refinement contract.
MESELSON_STAHL_PARENT_TEXT = (
    "DNA replication in E. coli is semiconservative: after replication, "
    "each daughter duplex retains one parental DNA subunit."
)
MESELSON_STAHL_OUTCOME_FIELDS: dict[str, Any] = {
    "method_protocol": (
        "Grow E. coli for many generations with 15NH4Cl, shift to medium "
        "with a ten-fold excess of 14NH4Cl, and separate DNA by equilibrium "
        "sedimentation in a CsCl density gradient."
    ),
    "conditions": (
        "Exponential growth after the isotope shift; observe DNA after one "
        "and two generation cycles."
    ),
    "measured_observation": (
        "After one generation, only the intermediate-density hybrid band "
        "is present. After the second, equal amounts of intermediate-density "
        "hybrid and light DNA are present."
    ),
    "units": (
        "Density-band class and relative amount; second-cycle amounts are 1:1."
    ),
    "controls": (
        "Keep the published heavy-15N starting position and light-14N "
        "density position as band references. Add no unreported replicate "
        "count or separate control cohort."
    ),
    "interpretation": (
        "The band pattern is consistent with semiconservative replication; "
        "this interpretation remains distinct from the measured bands."
    ),
}


def _add_meselson_stahl_fixture(
    run_id: str, db_path: str
) -> tuple[str, dict[str, Any], list[str]]:
    """Persist the contract's parent and ordered source metadata."""
    parent_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="Semiconservative DNA replication in E. coli",
            statement=MESELSON_STAHL_PARENT_TEXT,
        ),
        db_path=db_path,
    )
    source_ids = [
        store.add_evidence(
            store.NewEvidence(
                run_id=run_id,
                title="The replication of DNA in Escherichia coli",
                source="pubmed",
                url="https://pmc.ncbi.nlm.nih.gov/articles/PMC528642/",
                doi="10.1073/pnas.44.7.671",
                pmid="16590258",
                abstract=(
                    "Full text and abstracts are outside this metadata-only "
                    "fixture."
                ),
            ),
            db_path=db_path,
        ),
        store.add_evidence(
            store.NewEvidence(
                run_id=run_id,
                title="Hanawalt's historical account",
                source="pmc",
                url="https://pmc.ncbi.nlm.nih.gov/articles/PMC539797/",
            ),
            db_path=db_path,
        ),
    ]
    outcome_fields = {
        **MESELSON_STAHL_OUTCOME_FIELDS,
        "referenced_evidence_ids": source_ids,
    }
    return parent_id, outcome_fields, source_ids


def _record_meselson_stahl_outcome(
    client: Any, run_id: str, owner: str, db_path: str
) -> tuple[str, dict[str, Any], list[str], Any]:
    """Record the frozen outcome through the authenticated public endpoint."""
    parent_id, outcome_fields, source_ids = _add_meselson_stahl_fixture(
        run_id, db_path
    )
    response = client.post(
        f"/api/runs/{run_id}/hypotheses/{parent_id}/outcomes",
        headers=_signed_headers(owner),
        json=outcome_fields,
    )
    return parent_id, outcome_fields, source_ids, response


def _signed_headers(owner: str) -> dict[str, str]:
    token = auth.create_session_token(owner)
    return {"Authorization": f"Bearer {token}"}


def _outcome_body(evidence_id: str | None = None) -> dict[str, Any]:
    return {
        "method_protocol": "24-hour viability assay",
        "conditions": "10 micromolar treatment X, n=4",
        "measured_observation": "Mean growth was 18% lower than vehicle.",
        "units": "%",
        "controls": "Vehicle-treated cells",
        "interpretation": "The result is consistent with the proposed effect.",
        "referenced_evidence_ids": [evidence_id] if evidence_id else [],
    }


def _add_hypothesis(run_id: str, db_path: str, title: str) -> str:
    return store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title=title,
            statement=f"{title} by pathway Y.",
        ),
        db_path=db_path,
    )


def _new_run(client: Any, owner: str) -> str:
    response = client.post(
        "/api/runs",
        headers=_signed_headers(owner),
        json={"research_goal": "Measure the proposed effect"},
    )
    assert response.status_code == 200
    return str(response.json()["id"])


def _save_engine_checkpoint(
    run_id: str,
    hypothesis: Hypothesis,
    db_path: str,
) -> None:
    event_seq = store.latest_event_seq(run_id, db_path=db_path)
    envelope = serialize_workflow_state(
        {"hypotheses": [hypothesis]},
        last_event_seq=event_seq,
    )
    store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage="completed",
            schema_version=1,
            last_event_seq=event_seq,
            state={"provider": "engine", **envelope},
        ),
        db_path=db_path,
    )
