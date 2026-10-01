"""Pin existing JSON reads before adding response validation."""

from typing import Any

from fastapi.testclient import TestClient

from app import store
from app.main import app


def _legacy_run(isolated_db: str) -> str:
    """Persist the minimal saved-report shape supported by existing reads."""
    run = store.create_run(
        "Study feedback",
        "standard",
        "mock",
        {"old_knob": [1, None]},
        store.RunCreateOptions(client_id="contract-owner", db_path=isolated_db),
    )
    store.save_report(
        run.id,
        {"leaderboard": [], "older_section": {"retained": True}},
        "# Saved report",
        db_path=isolated_db,
    )
    return run.id


def _read(client: TestClient, path: str) -> Any:
    """Read an owner-facing JSON response with the existing client identity."""
    response = client.get(path, headers={"X-Client-ID": "contract-owner"})
    assert response.status_code == 200, response.text
    return response.json()


def test_run_reads_keep_nullable_and_unmodeled_persisted_fields(
    isolated_db: str,
) -> None:
    run_id = _legacy_run(isolated_db)
    with TestClient(app) as client:
        run = _read(client, f"/api/runs/{run_id}")
        assert run["completed_at"] is None and run["error"] is None
        assert run["config"]["old_knob"] == [1, None]
        assert run["execution_policy"] == "standard"
        assert run["summary"]["hypotheses"] == 0
        listed = _read(client, "/api/runs")["runs"][0]
        assert "summary" not in listed
        assert listed["top_hypotheses"] == []


def test_old_report_and_public_projection_keep_their_exact_shapes(
    isolated_db: str,
) -> None:
    run_id = _legacy_run(isolated_db)
    with TestClient(app) as client:
        report = _read(client, f"/api/runs/{run_id}/report")
        assert report["payload"] == {
            "leaderboard": [],
            "older_section": {"retained": True},
        }
        created = client.post(
            f"/api/runs/{run_id}/shares",
            headers={"X-Client-ID": "contract-owner"},
        )
        assert created.status_code == 200
        shared = client.get(f"/api/shared/{created.json()['token']}").json()
        assert set(shared["run"]) == {"title", "research_goal", "run_mode"}
        assert shared["report"] == report


def test_curated_reports_validate_all_nonempty_collection_shapes(
    isolated_db: str,
) -> None:
    """Real seeded rows exercise nested models as well as empty envelopes."""
    with TestClient(app) as client:
        demos = client.get("/api/runs/demo")
        assert demos.status_code == 200
        for run in demos.json()["runs"]:
            for name in (
                "hypotheses",
                "evidence",
                "matches",
                "proximity",
                "reviews",
                "safety",
                "claim-evidence",
                "messages",
                "report",
            ):
                response = client.get(f"/api/runs/{run['id']}/{name}")
                assert response.status_code == 200, (name, response.text)
                if name in ("hypotheses", "evidence", "matches", "reviews"):
                    assert response.json()[name]
