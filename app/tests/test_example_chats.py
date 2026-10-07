from __future__ import annotations

import asyncio
import json

from co_scientist.domains.chat import seed
from co_scientist.domains.chat.repository import examples, interviews
from co_scientist.domains.research_state.repository import hypotheses, records
from co_scientist.platform import db
from co_scientist.platform.db.models import DEMO_CLIENT_ID

from app.store import reports, runs_views


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
    assert all(not h["parent_id"] or h["parent_id"] in new_ids for h in clone_hyps)
    assert {h["elo_rating"] for h in source_hyps} == {h["elo_rating"] for h in clone_hyps}
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
