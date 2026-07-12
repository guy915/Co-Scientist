"""End-to-end tests for revocable public Goal Report capabilities."""

from fastapi.testclient import TestClient

from app import store
from app.main import app


def test_share_link_is_unique_hashed_and_revocable(isolated_db: str) -> None:
    """Owner creation hashes the token; revocation closes public access."""
    run = store.create_run(
        "Study a causal pathway",
        "standard",
        "mock",
        {},
        client_id="owner-a",
        db_path=isolated_db,
    )
    store.save_report(
        run.id,
        {"research_goal": run.research_goal, "leaderboard": []},
        "# Goal Report",
        db_path=isolated_db,
    )
    with TestClient(app) as client:
        denied = client.post(
            f"/api/runs/{run.id}/shares",
            headers={"X-Client-ID": "other"},
        )
        assert denied.status_code == 404

        created = client.post(
            f"/api/runs/{run.id}/shares",
            headers={"X-Client-ID": "owner-a"},
        )
        assert created.status_code == 200
        share = created.json()
        assert len(share["token"]) >= 32

        with store.connect(isolated_db) as conn:
            stored = conn.execute(
                "SELECT token_hash FROM report_shares WHERE id=?",
                (share["id"],),
            ).fetchone()[0]
        assert stored != share["token"]

        public = client.get(f"/api/shared/{share['token']}")
        assert public.status_code == 200
        assert public.json()["report"]["payload"]["research_goal"] == (
            "Study a causal pathway"
        )

        revoked = client.delete(
            f"/api/runs/{run.id}/shares/{share['id']}",
            headers={"X-Client-ID": "owner-a"},
        )
        assert revoked.status_code == 204
        assert client.get(f"/api/shared/{share['token']}").status_code == 404
