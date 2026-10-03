from __future__ import annotations

import time
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app import store
from app.config import settings
from app.main import app
from app.runs.models import CreateRunRequest
from tests._client import make_client
from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status


def _new_run(c: TestClient, goal: str, *, tier: str = "express") -> str:
    res = c.post("/api/runs", json={"research_goal": goal, "tier": tier})
    return cast(str, res.json()["id"])


def test_create_run_rejects_empty_goal() -> None:
    c = _client()
    res = c.post("/api/runs", json={"research_goal": "", "profile": "standard"})
    assert res.status_code == 422


def test_create_run_defaults_run_mode() -> None:
    c = _client()
    res = c.post("/api/runs", json={"research_goal": "x"})
    assert res.status_code == 200
    assert res.json()["run_mode"] == "standard"


@pytest.mark.parametrize("tier", ["express", "standard", "extended", "ultra"])
def test_create_run_accepts_every_tier(tier: str) -> None:
    client = _client()
    response = client.post(
        "/api/runs", json={"research_goal": "x", "tier": tier}
    )
    assert response.status_code == 200
    assert response.json()["run_mode"] == tier


def test_create_run_rejects_unknown_tier() -> None:
    client = _client()
    response = client.post(
        "/api/runs", json={"research_goal": "x", "tier": "gigantic"}
    )
    assert response.status_code == 422


def test_concurrency_ceiling_is_uniform_and_per_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Per-client concurrency limits apply independently to each owner at every
    # tier.
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(settings, "max_concurrent_runs", 2)
    client = _client()

    def start_runs(scientist: str, tier: str, count: int) -> list[int]:
        headers = {"X-Client-ID": scientist}
        codes = []
        for index in range(count):
            run_id = client.post(
                "/api/runs",
                headers=headers,
                json={"research_goal": f"{tier} {index}", "tier": tier},
            ).json()["id"]
            codes.append(
                client.post(
                    f"/api/runs/{run_id}/start", headers=headers, json={}
                ).status_code
            )
        return codes

    assert start_runs("scientist-a", "ultra", 3) == [200, 200, 409]
    assert start_runs("scientist-b", "ultra", 1) == [200]


def test_get_run_returns_404_for_unknown_id() -> None:
    c = _client()
    res = c.get("/api/runs/not-a-real-id")
    assert res.status_code == 404


def test_starting_a_completed_run_is_a_conflict() -> None:
    c = _client()
    rid = _new_run(c, "Mechanisms of selective autophagy")
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "completed", timeout=20.0)
    again = c.post(f"/api/runs/{rid}/start", json={})
    assert again.status_code == 409


def test_cancel_draft_run_without_handle_marks_it_cancelled() -> None:
    c = _client()
    rid = _new_run(c, "Inactive cancel test")
    res = c.post(f"/api/runs/{rid}/cancel")
    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"
    assert c.get(f"/api/runs/{rid}").json()["status"] == "cancelled"


def test_cancel_restart_survivor_marks_it_cancelled() -> None:
    from app import store
    from app.store import RunStatus

    c = _client()
    rid = _new_run(c, "Restart survivor cancel")
    store.update_run_status(rid, RunStatus.RUNNING)
    queued = store.enqueue_task(
        store.NewTask(
            run_id=rid,
            task_type="engine.node.ranking",
            inputs={},
            idempotency_key="cancel-api-task",
        )
    )

    res = c.post(f"/api/runs/{rid}/cancel")

    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"
    assert c.get(f"/api/runs/{rid}").json()["status"] == "cancelled"
    cancelled = store.get_task(queued.id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    events = store.list_events(rid)
    assert any(
        e["type"] == "status" and e["payload"].get("status") == "cancelled"
        for e in events
    )


def test_engine_queue_can_pause_and_resume_without_process_handle(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import store

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    c = _client()
    rid = _new_run(c, "Durable pause test")
    started = c.post(f"/api/runs/{rid}/start", json={})
    assert started.status_code == 200

    paused = c.post(f"/api/runs/{rid}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    [task] = store.list_tasks(rid, db_path=isolated_db)
    assert task.status == "paused"

    resumed = c.post(f"/api/runs/{rid}/resume")
    assert resumed.status_code == 200
    [task] = store.list_tasks(rid, db_path=isolated_db)
    assert task.status == "queued"


def test_cancel_completed_run_conflicts() -> None:
    c = _client()
    rid = _new_run(c, "Cancel a finished run")
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "completed", timeout=20.0)
    res = c.post(f"/api/runs/{rid}/cancel")
    assert res.status_code == 409


def test_report_md_404_before_completion() -> None:
    c = _client()
    rid = _new_run(c, "Pre-completion report fetch")
    res = c.get(f"/api/runs/{rid}/report.md")
    assert res.status_code == 404


def test_report_md_has_attachment_disposition_after_completion() -> None:
    c = _client()
    rid = _new_run(c, "Attachment header test")
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "completed", timeout=20.0)
    res = c.get(f"/api/runs/{rid}/report.md")
    assert res.status_code == 200
    assert "attachment" in res.headers.get("content-disposition", "").lower()
    assert rid in res.headers.get("content-disposition", "")
    assert "Research Report" in res.text
    assert "## Top hypotheses" in res.text


def test_run_listing_returns_most_recent_first() -> None:
    c = _client()
    a = _new_run(c, "Run A")
    time.sleep(0.05)
    b = _new_run(c, "Run B")
    listing = c.get("/api/runs").json()["runs"]
    ids = [r["id"] for r in listing]
    assert ids.index(b) < ids.index(a)


def test_status_endpoint_includes_provider_and_backend() -> None:
    c = _client()
    res = c.get("/status")
    assert res.status_code == 200
    data = res.json()
    assert data["provider"] == "engine"
    assert data["llm_backend"] == "offline"


def test_run_get_includes_summary_counts() -> None:
    c = _client()
    rid = _new_run(c, "Summary test")
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "completed", timeout=20.0)
    res = c.get(f"/api/runs/{rid}").json()
    assert "summary" in res
    summary = res["summary"]
    assert summary["events"] >= 10
    assert summary["hypotheses"] >= 2
    assert summary["matches"] >= 2


def test_active_run_counts_committed_checkpoint_artifacts(
    isolated_db: str,
) -> None:
    client = _client()
    run = store.create_run(
        "Live summary",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(client_id="live-owner", db_path=isolated_db),
    )
    store.update_run_status(
        run.id, store.RunStatus.RUNNING, db_path=isolated_db
    )
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="engine_task:test",
            schema_version=1,
            last_event_seq=0,
            state={
                "provider": "engine",
                "state": {
                    "hypotheses": [{"id": "h1"}, {"id": "h2"}],
                    "articles": [{"id": "a1"}],
                },
            },
        ),
        db_path=isolated_db,
    )

    response = client.get(
        f"/api/runs/{run.id}", headers={"X-Client-ID": "live-owner"}
    )

    assert response.status_code == 200
    assert response.json()["summary"]["hypotheses"] == 2
    assert response.json()["summary"]["evidence"] == 1


def test_safety_block_at_intake_short_circuits_workflow() -> None:
    c = _client()
    rid = _new_run(
        c,
        "Engineer smallpox virus to enhance "
        "human-to-human transmission and lethality",
    )
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "blocked", timeout=10.0)
    hyps = c.get(f"/api/runs/{rid}/hypotheses").json()["hypotheses"]
    assert hyps == []
    safety = c.get(f"/api/runs/{rid}/safety").json()["safety"]
    assert any(
        s["decision"] == "block" and s["stage"] == "intake" for s in safety
    )


def test_stray_audience_field_is_ignored() -> None:
    # Ignore legacy extra fields sent by cached frontends.
    req = CreateRunRequest(research_goal="goal", audience="sbi_ucd")

    assert not hasattr(req, "audience")


_TIERS = ("express", "standard", "extended", "ultra")


def test_ceiling_is_configurable() -> None:
    assert settings.max_concurrent_runs >= 3


def _start(client: TestClient, headers: dict[str, str], tier: str) -> int:
    run_id = client.post(
        "/api/runs",
        headers=headers,
        json={"research_goal": f"{tier} question", "tier": tier},
    ).json()["id"]
    started = client.post(f"/api/runs/{run_id}/start", headers=headers, json={})
    return int(started.status_code)


def test_ceiling_is_one_total_across_tiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    monkeypatch.setattr(settings, "max_concurrent_runs", 2)
    client = make_client()
    headers = {"X-Client-ID": "tier-hopper"}

    codes = [_start(client, headers, tier) for tier in _TIERS]

    assert codes == [200, 200, 409, 409]


# First-match routing makes demo/run-id order significant; authentication
# middleware remains independent.


# One operation per line so a diff names exactly which route changed; the
# generated operation ids are too long to wrap without hiding that.
# ruff: noqa: E501


EXPECTED = [
    "POST /api/runs | create_run_api_runs_post |  | CreateRunRequest | 200,422",
    "GET /api/runs | list_runs_api_runs_get | query:limit |  | 200,422",
    "GET /api/runs/demo | list_demo_runs_api_runs_demo_get |  |  | 200",
    "GET /api/runs/{run_id} | get_run_api_runs__run_id__get | path:run_id* |  | 200,422",
    "PATCH /api/runs/{run_id} | rename_run_api_runs__run_id__patch | path:run_id* | RenameRunRequest | 200,422",
    "DELETE /api/runs/{run_id} | delete_run_api_runs__run_id__delete | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/start | start_run_api_runs__run_id__start_post | path:run_id* | StartRunRequest | 200,422",
    "POST /api/runs/{run_id}/cancel | cancel_run_api_runs__run_id__cancel_post | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/pause | pause_run_api_runs__run_id__pause_post | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/resume | resume_run_api_runs__run_id__resume_post | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/events | stream_events_api_runs__run_id__events_get | path:run_id*,query:after,query:stream |  | 200,422",
    "GET /api/runs/{run_id}/hypotheses | get_hypotheses_api_runs__run_id__hypotheses_get | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/hypotheses | add_human_hypothesis_api_runs__run_id__hypotheses_post | path:run_id* | HumanHypothesisRequest | 200,422",
    "GET /api/runs/{run_id}/evidence | get_evidence_api_runs__run_id__evidence_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/matches | get_matches_api_runs__run_id__matches_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/proximity | get_proximity_api_runs__run_id__proximity_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/reviews | get_reviews_api_runs__run_id__reviews_get | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/reviews | add_human_review_api_runs__run_id__reviews_post | path:run_id* | HumanReviewRequest | 200,422",
    "GET /api/runs/{run_id}/safety | get_safety_api_runs__run_id__safety_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/outcomes | get_hypothesis_outcomes_api_runs__run_id__outcomes_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/tasks | get_tasks_api_runs__run_id__tasks_get | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/safety/{decision_id}/adjudicate | adjudicate_safety_api_runs__run_id__safety__decision_id__adjudicate_post | path:run_id*,path:decision_id* | SafetyAdjudicationRequest | 200,422",
    "GET /api/runs/{run_id}/citations | get_citations_api_runs__run_id__citations_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/metrics | get_metrics_api_runs__run_id__metrics_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/logs | get_run_logs_api_runs__run_id__logs_get | path:run_id*,query:after_id,query:limit,query:min_level,query:q,query:verbose |  | 200,422",
    "GET /api/runs/{run_id}/claim-evidence | get_claim_evidence_api_runs__run_id__claim_evidence_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/knowledge-facts | get_knowledge_facts_api_runs__run_id__knowledge_facts_get | path:run_id*,query:kind,query:entity |  | 200,422",
    "GET /api/runs/{run_id}/supervisor-plan | get_supervisor_plan_api_runs__run_id__supervisor_plan_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/report | get_report_api_runs__run_id__report_get | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/report.md | get_report_markdown_api_runs__run_id__report_md_get | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/attachments | add_attachment_api_runs__run_id__attachments_post | path:run_id* | HumanAttachmentRequest | 200,422",
    "POST /api/runs/{run_id}/attachments/upload | upload_attachment_api_runs__run_id__attachments_upload_post | path:run_id* |  | 200,422",
    "GET /api/runs/{run_id}/attachments/search | search_attachments_api_runs__run_id__attachments_search_get | path:run_id*,query:q* |  | 200,422",
    "POST /api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes | record_hypothesis_outcome_api_runs__run_id__hypotheses__hypothesis_id__outcomes_post | path:run_id*,path:hypothesis_id* | HypothesisOutcomeRequest | 201,422",
    "POST /api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes/{outcome_id}/refine | request_hypothesis_outcome_refinement_api_runs__run_id__hypotheses__hypothesis_id__outcomes__outcome_id__refine_post | path:run_id*,path:hypothesis_id*,path:outcome_id*,header:Idempotency-Key* |  | 202,422",
    "GET /api/runs/{run_id}/hypotheses/{hypothesis_id}/outcomes/{outcome_id}/refine | get_hypothesis_outcome_refinement_api_runs__run_id__hypotheses__hypothesis_id__outcomes__outcome_id__refine_get | path:run_id*,path:hypothesis_id*,path:outcome_id* |  | 200,422",
    "POST /api/runs/{run_id}/messages | send_message_api_runs__run_id__messages_post | path:run_id* | SendMessageRequest | 200,422",
    "GET /api/runs/{run_id}/messages | list_messages_api_runs__run_id__messages_get | path:run_id* |  | 200,422",
    "POST /api/runs/{run_id}/messages/ask | ask_question_api_runs__run_id__messages_ask_post | path:run_id* | AskRequest | 200,422",
    "POST /api/runs/{run_id}/messages/started | announce_start_api_runs__run_id__messages_started_post | path:run_id* | StartAnnouncementRequest | 200,422",
]


def describe_routes() -> list[str]:
    rows = []
    for path, operations in app.openapi()["paths"].items():
        for method, op in operations.items():
            if op.get("tags") == ["runs"]:
                rows.append(_describe(method.upper(), path, op))
    return rows


def _describe(method: str, path: str, op: dict[str, Any]) -> str:
    params = ",".join(
        f"{p['in']}:{p['name']}{'*' if p['required'] else ''}"
        for p in op.get("parameters", [])
    )
    body = (
        op.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
        .get("$ref", "")
        .rsplit("/", 1)[-1]
    )
    codes = ",".join(sorted(op["responses"]))
    return (
        f"{method} {path} | {op['operationId']} | {params} | {body} | {codes}"
    )


def test_run_route_table_is_unchanged() -> None:
    assert describe_routes() == EXPECTED
