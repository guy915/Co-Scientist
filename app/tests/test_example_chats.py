from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

from app import seed
from app.store import (
    db,
    examples,
    hypotheses,
    interviews,
    messages,
    records,
    reports,
    runs_views,
)
from app.store.models import DEMO_CLIENT_ID
from tests._client import make_client


def _example(db_path: str) -> str:
    asyncio.run(seed.seed_demo_runs(db_path))
    return runs_views.list_runs(client_id=DEMO_CLIENT_ID, db_path=db_path)[0].id


def test_private_copy_preserves_lineage_reviews_evidence_report_and_no_tasks(
    isolated_db: str,
) -> None:
    source_id = _example(isolated_db)
    chat = examples.open_example_chat(source_id, "owner")
    clone_id = interviews.run_id_for_interview(chat["id"], "owner")
    assert clone_id and clone_id != source_id
    source_hyps = hypotheses.list_hypotheses(source_id)
    clone_hyps = hypotheses.list_hypotheses(clone_id)
    assert len(source_hyps) == len(clone_hyps)
    old_ids = {h["id"] for h in source_hyps}
    new_ids = {h["id"] for h in clone_hyps}
    assert not old_ids & new_ids
    assert all(
        not h["parent_id"] or h["parent_id"] in new_ids for h in clone_hyps
    )
    assert {h["elo_rating"] for h in source_hyps} == {
        h["elo_rating"] for h in clone_hyps
    }
    for reader in (
        records.list_evidence,
        records.list_reviews,
        records.list_matches,
        records.list_claim_evidence,
    ):
        assert len(reader(source_id)) == len(reader(clone_id))
    report = reports.get_latest_report(clone_id)
    assert report and "Curated demonstration only" in report["markdown_text"]
    assert not any(identity in json.dumps(report) for identity in old_ids)
    with db.connect() as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM scientific_tasks WHERE run_id=?",
                (clone_id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM run_credentials WHERE run_id=?",
                (clone_id,),
            ).fetchone()[0]
            == 0
        )


def test_open_is_idempotent_under_concurrent_tabs_and_isolates_owners(
    isolated_db: str,
) -> None:
    source_id = _example(isolated_db)
    with ThreadPoolExecutor(max_workers=3) as pool:
        chats = list(
            pool.map(
                lambda _: examples.open_example_chat(source_id, "owner"),
                range(3),
            )
        )
    assert len({chat["id"] for chat in chats}) == 1
    assert len(runs_views.list_runs(client_id="owner")) == 1
    other = examples.open_example_chat(source_id, "other")
    assert other["id"] != chats[0]["id"]


def test_api_continues_owned_chat_without_mutating_shared_example(
    isolated_db: str,
) -> None:
    source_id = _example(isolated_db)
    with make_client() as client:
        client.headers["X-Client-ID"] = "owner"
        response = client.post(f"/api/runs/{source_id}/example-chat")
        assert response.status_code == 200, response.text
        chat_id = response.json()["id"]
        chat = client.get(f"/api/interviews/{chat_id}").json()
        clone_id = chat["run_id"]
        before = len(messages.list_messages(source_id))
        answer = client.post(
            f"/api/runs/{clone_id}/messages/ask",
            json={"question": "Which idea needs replication?"},
        )
        assert answer.status_code == 200 and '"type": "done"' in answer.text
        assert len(messages.list_messages(source_id)) == before
        assert len(messages.list_messages(clone_id)) == before + 2
        assert (
            client.post(
                f"/api/runs/{source_id}/messages/ask",
                json={"question": "Do not change shared text"},
            ).status_code
            == 403
        )
        assert client.get(f"/api/runs/{source_id}").status_code == 200
    with make_client() as client:
        client.headers["X-Client-ID"] = "other"
        assert client.get(f"/api/interviews/{chat_id}").status_code == 404
        assert client.get(f"/api/runs/{clone_id}").status_code == 404
        assert (
            client.post(f"/api/runs/{clone_id}/example-chat").status_code == 404
        )
