from __future__ import annotations

import asyncio
import io
import pathlib
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from threading import Barrier
from typing import Any

import pytest
from co_scientist.exceptions import FreeModelEligibilityError
from co_scientist.llm import current_api_key
from co_scientist.scheduling import (
    Budget,
    SchedulerStats,
    TaskType,
    TerminationReason,
)
from co_scientist.scheduling.policy import (
    decide_next_task,
)
from fastapi.testclient import TestClient

from app import async_bridge, credentials, engine_tasks, run_modes, task_worker
from app.config import settings
from app.engine_adapter.opts import _generator_kwargs
from app.run_modes import RUN_TIER_DEFAULTS
from app.store import db, documents, logs, runs, tasks
from app.store import receipts as store_receipts
from app.store.models import DEMO_CLIENT_ID, RunStatus, ScientificTask
from app.store.runs import RunCreateOptions
from tests._client import append_log_row, make_client, wait_for
from tests._client import create_run as _create_run
from tests._store_helpers import enqueue_task, seed_run

from ._llm_fake_backend import install_completion_backend


@pytest.mark.parametrize("mode", ["blocked_paid", "campaign_free", "user_byok"])
@pytest.mark.parametrize("recovered", [False, True])
@pytest.mark.parametrize("auxiliary", ["claim", "safety"])
async def test_durable_auxiliary_admission_with_stored_credential(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    recovered: bool,
    auxiliary: str,
    mode: str,
) -> None:
    from co_scientist.llm.admission import free_policy as free_catalog

    from app.claims import verifier as claim_verifier
    from app.safety import semantic as safety_semantic

    monkeypatch.setattr(settings, "byok_encryption_key", "campaign-test-secret")
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    free_catalog.install_catalog_reader(
        free_catalog.CatalogReader(
            lambda: {
                "campaign/free:free": {
                    "pricing": {"prompt": "0", "completion": "0"},
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                }
            }
        )
    )
    run = seed_run(
        "public research",
        options=RunCreateOptions(
            execution_policy=("standard" if mode == "user_byok" else "campaign")
        ),
    )
    credential = credentials.ByokCredential(
        "openrouter",
        "stored-test-key",
        "openrouter/campaign/free:free"
        if mode == "campaign_free"
        else "openrouter/campaign/paid",
    )
    credentials.store_run_credential(
        run.id, "test-owner", credential, isolated_db
    )
    task = enqueue_task(
        run.id, "engine.node.generate", "campaign-check", db_path=isolated_db
    )
    if recovered:
        claimed = tasks.claim_task(
            "lost-worker", run_id=run.id, db_path=isolated_db
        )
        assert claimed is not None
        with db.connect(isolated_db) as conn:
            conn.execute(
                "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
                (task.id,),
            )

    sent: list[dict[str, Any]] = []

    async def transport(**kwargs: Any) -> Any:
        sent.append(kwargs)
        raise FreeModelEligibilityError("test transport reached")

    install_completion_backend(monkeypatch, transport)

    calls = {
        "claim": partial(
            claim_verifier._call_claim_json_async,
            "deployment",
            claim_verifier._EntailmentRequest(
                lambda: claim_verifier._entailment_prompt("claim", []),
                claim_verifier._ENTAILMENT_DRAFT_SCHEMA,
                claim_verifier._MAX_TOKENS,
                "claim_verifier",
            ),
        ),
        "safety": partial(
            safety_semantic._call_semantic_safety_model,
            "public goal",
            "intake",
            "deployment",
        ),
    }

    async def assess() -> None:
        assert current_api_key() == credential.api_key
        assert credentials.current_byok() == credential
        with pytest.raises(FreeModelEligibilityError):
            await calls[auxiliary]()

    async def dispatch(
        task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        await asyncio.create_task(assess())
        await async_bridge.run_off_loop(
            lambda: async_bridge.run_coroutine_sync(assess)
        )
        return {"checked": auxiliary}

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", dispatch)
    assert credentials.current_byok() is None
    assert current_api_key() is None
    assert await task_worker.run_once(
        "fresh-worker", run_id=run.id, db_path=isolated_db
    )
    saved = tasks.get_task(task.id, db_path=isolated_db)
    assert saved is not None and saved.status == "completed"
    assert saved.result == {"checked": auxiliary}
    assert saved.attempt == (2 if recovered else 1)
    assert len(sent) == (0 if mode == "blocked_paid" else 2)
    _assert_requests(sent, credential, mode)
    assert credentials.current_byok() is None
    assert current_api_key() is None


def _assert_requests(
    sent: list[dict[str, Any]],
    credential: credentials.ByokCredential,
    mode: str,
) -> None:
    for request in sent:
        assert request["api_key"] == credential.api_key
        assert request["model"] == credential.model
        if mode == "campaign_free":
            assert request["extra_body"]["provider"]["max_price"] == {
                "prompt": 0,
                "completion": 0,
                "request": 0,
            }
        else:
            assert request.get("extra_body", {}).get("provider", {}).get(
                "max_price"
            ) != {"prompt": 0, "completion": 0, "request": 0}


# Landing tier figures are hardcoded before API calls, so they must track
# backend defaults.


_CONTENT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "frontend/src/workbench/pages/home_landing_content.ts"
)
_TIER = re.compile(
    r"\{name: '(\w+)', seeds: (\d+), cycles: (\d+), maxIdeas: (\d+)\}"
)


def test_landing_tiers_match_run_tier_defaults() -> None:
    rows = _TIER.findall(_CONTENT.read_text(encoding="utf-8"))
    shown = {
        name.lower(): (int(seeds), int(cycles), int(max_ideas))
        for name, seeds, cycles, max_ideas in rows
    }
    expected = {
        tier: (
            values["initial_hypotheses_count"],
            values["max_iterations"],
            values["max_ideas"],
        )
        for tier, values in RUN_TIER_DEFAULTS.items()
    }
    assert shown == expected


_IDEMPOTENCY_OWNER = "idempotency-owner"
_IDEMPOTENCY_KEY = "run-create-01"
_IDEMPOTENCY_PAYLOAD = {
    "research_goal": "Study a defined signaling pathway",
    "tier": "express",
}


def _idempotency_post_run(
    client: Any,
    *,
    owner: str = _IDEMPOTENCY_OWNER,
    request_key: str | None = _IDEMPOTENCY_KEY,
    payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    headers = {"X-Client-ID": owner}
    if request_key is not None:
        headers["Idempotency-Key"] = request_key
    headers.update(extra_headers or {})
    return client.post(
        "/api/runs", json=payload or _IDEMPOTENCY_PAYLOAD, headers=headers
    )


def _owned_run_ids(client: Any, owner: str = _IDEMPOTENCY_OWNER) -> list[str]:
    response = client.get("/api/runs", headers={"X-Client-ID": owner})
    assert response.status_code == 200, response.text
    return [run["id"] for run in response.json()["runs"]]


def test_idempotency_key_replays_conflicts_and_is_scoped_to_its_owner() -> None:
    client = make_client()
    first = _idempotency_post_run(client)
    retry = _idempotency_post_run(client)
    changed = _idempotency_post_run(
        client,
        payload={**_IDEMPOTENCY_PAYLOAD, "research_goal": "Another pathway"},
    )
    other_owner = _idempotency_post_run(client, owner="owner-two")

    assert first.status_code == retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]
    assert changed.status_code == 409
    assert other_owner.status_code == 200
    assert other_owner.json()["id"] != first.json()["id"]
    assert _owned_run_ids(client) == [first.json()["id"]]
    assert _owned_run_ids(client, "owner-two") == [other_owner.json()["id"]]


def test_concurrent_exact_retries_create_one_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client()
    admitted_together = Barrier(2)
    lookup = store_receipts.lookup_run_creation_receipt

    def synchronize_admission(
        owner: str,
        key: str,
        *,
        db_path: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> store_receipts.RunCreationReceipt | None:
        receipt = lookup(owner, key, db_path=db_path, conn=conn)
        # Synchronize after both unlocked lookups, before either writer commits.
        if conn is None:
            admitted_together.wait(timeout=5)
        return receipt

    monkeypatch.setattr(
        store_receipts, "lookup_run_creation_receipt", synchronize_admission
    )

    def submit() -> Any:
        return _idempotency_post_run(client)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [
            future.result(timeout=10)
            for future in (pool.submit(submit), pool.submit(submit))
        ]

    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    run_ids = {response.json()["id"] for response in responses}
    assert len(run_ids) == 1
    assert _owned_run_ids(client) == list(run_ids)


@pytest.mark.parametrize(
    "request_key", ["contains spaces", "bad/key", "x" * 129]
)
def test_malformed_idempotency_key_is_rejected(request_key: str) -> None:
    client = make_client()
    response = _idempotency_post_run(client, request_key=request_key)

    assert response.status_code == 400
    assert _owned_run_ids(client) == []


def test_changed_byok_key_conflicts_without_echoing_either_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings, "byok_encryption_key", "test-encryption-secret"
    )
    validated: list[str] = []

    async def accept_credential(
        credential: credentials.ByokCredential,
    ) -> None:
        validated.append(credential.api_key)
        return None

    async def no_model_call(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        credentials, "validate_byok_credential", accept_credential
    )
    monkeypatch.setattr("app.runs.crud.generate_run_title", no_model_call)
    monkeypatch.setattr(
        "app.runs.crud.generate_goal_restatement", no_model_call
    )

    client = make_client()
    first_secret = "sk-first-private-value"
    changed_secret = "sk-changed-private-value"
    byok_headers = {"X-LLM-Provider": "deepseek"}
    first = _idempotency_post_run(
        client,
        extra_headers={**byok_headers, "X-LLM-API-Key": first_secret},
    )
    changed = _idempotency_post_run(
        client,
        extra_headers={**byok_headers, "X-LLM-API-Key": changed_secret},
    )

    assert first.status_code == 200
    assert changed.status_code == 409
    assert first_secret not in changed.text
    assert changed_secret not in changed.text
    assert _owned_run_ids(client) == [first.json()["id"]]
    assert validated == [first_secret]


def test_concurrent_changed_payloads_commit_one_same_key_run(
    isolated_db: str,
) -> None:
    client = make_client()
    owner = "changed-race-owner"
    key = "changed-payload-race"
    payloads = (
        _IDEMPOTENCY_PAYLOAD,
        {**_IDEMPOTENCY_PAYLOAD, "research_goal": "Study a different pathway"},
    )
    start_together = Barrier(len(payloads))

    def submit(payload: dict[str, Any]) -> Any:
        start_together.wait(timeout=5)
        return _idempotency_post_run(
            client, owner=owner, request_key=key, payload=payload
        )

    with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
        futures = [pool.submit(submit, payload) for payload in payloads]
        responses = [future.result(timeout=10) for future in futures]

    assert sorted(response.status_code for response in responses) == [200, 409]
    accepted = next(
        response for response in responses if response.status_code == 200
    )
    listed = client.get("/api/runs", headers={"X-Client-ID": owner})
    assert listed.status_code == 200, listed.text
    assert [run["id"] for run in listed.json()["runs"]] == [
        accepted.json()["id"]
    ]

    with sqlite3.connect(isolated_db) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM runs WHERE client_id=?", (owner,)
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM run_creation_receipts "
                "WHERE client_id=? AND idempotency_key=?",
                (owner, key),
            ).fetchone()[0]
            == 1
        )


_ROLLBACK_OWNER = "run-rollback-owner"
_ROLLBACK_KEY = "rollback-run-01"


def test_late_setup_failure_rolls_back_every_effect_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "byok_encryption_key", "rollback-test-secret")

    async def accept_credential(
        _credential: credentials.ByokCredential,
    ) -> None:
        return None

    async def no_model_call(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        credentials, "validate_byok_credential", accept_credential
    )
    monkeypatch.setattr("app.runs.crud.generate_run_title", no_model_call)
    monkeypatch.setattr(
        "app.runs.crud.generate_goal_restatement", no_model_call
    )
    client = make_client()
    staged = client.post(
        "/api/documents",
        headers={"X-Client-ID": _ROLLBACK_OWNER},
        files={
            "file": ("notes.txt", io.BytesIO(b"Pathway notes"), "text/plain")
        },
        data={"consent": "true"},
    )
    assert staged.status_code == 200, staged.text
    document_id = staged.json()["id"]
    payload: dict[str, Any] = {
        "research_goal": "Study this pathway",
        "tier": "express",
        "document_ids": [document_id],
    }
    provider_key = "sk-rollback-private-value"
    headers = {
        "X-Client-ID": _ROLLBACK_OWNER,
        "Idempotency-Key": _ROLLBACK_KEY,
        "X-LLM-Provider": "deepseek",
        "X-LLM-API-Key": provider_key,
    }

    add_receipt = store_receipts.add_run_creation_receipt

    def fail_after_receipt(*args: Any, **kwargs: Any) -> None:
        add_receipt(*args, **kwargs)
        raise RuntimeError("injected late setup failure")

    with monkeypatch.context() as patch:
        patch.setattr(
            store_receipts, "add_run_creation_receipt", fail_after_receipt
        )
        with pytest.raises(RuntimeError, match="injected late setup failure"):
            client.post("/api/runs", headers=headers, json=payload)

    assert (
        client.get(
            "/api/runs", headers={"X-Client-ID": _ROLLBACK_OWNER}
        ).json()["runs"]
        == []
    )
    document = documents.get_staged_documents([document_id], _ROLLBACK_OWNER)[0]
    assert document["run_id"] is None
    with db.connect() as conn:
        for table in (
            "runs",
            "run_events",
            "evidence",
            "run_credentials",
            "run_creation_receipts",
        ):
            assert (
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            )

    retried = client.post("/api/runs", headers=headers, json=payload)
    assert retried.status_code == 200, retried.text
    assert (
        documents.get_staged_documents([document_id], _ROLLBACK_OWNER)[0][
            "run_id"
        ]
        == (retried.json()["id"])
    )
    with db.connect() as conn:
        digest = conn.execute(
            "SELECT request_digest FROM run_creation_receipts WHERE run_id=?",
            (retried.json()["id"],),
        ).fetchone()[0]
    assert provider_key not in digest


_DELETION_OWNER = {"X-Client-ID": "delete-owner"}
_DELETION_OTHER = {"X-Client-ID": "someone-else"}


def _wait_owned_status(
    client: TestClient, run_id: str, status: str, *, timeout: float = 30.0
) -> bool:
    # Poll with the explicit owner identity; a default client cannot read
    # another identity's run.

    def _reached() -> bool:
        response = client.get(f"/api/runs/{run_id}", headers=_DELETION_OWNER)
        return response.status_code == 200 and bool(
            response.json().get("status") == status
        )

    return wait_for(_reached, timeout=timeout)


def _run_to_completion(client: TestClient, goal: str) -> str:
    created = _create_run(client, goal, headers=_DELETION_OWNER, tier="express")
    assert created.status_code == 200, created.text
    run_id: str = created.json()["id"]
    started = client.post(
        f"/api/runs/{run_id}/start", headers=_DELETION_OWNER, json={}
    )
    assert started.status_code == 200, started.text
    assert _wait_owned_status(client, run_id, "completed")
    return run_id


def test_delete_cascades_across_every_run_scoped_table(
    isolated_db: str,
) -> None:
    client = make_client()
    run_id = _run_to_completion(client, "Cascade delete goal")

    before = runs.count_run_rows(run_id, db_path=isolated_db)
    assert before["runs"] == 1
    assert before["hypotheses"] > 0
    assert before["reports"] > 0
    nonzero_tables = [t for t, n in before.items() if n > 0]
    assert len(nonzero_tables) >= 4

    response = client.delete(f"/api/runs/{run_id}", headers=_DELETION_OWNER)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted"] is True
    assert body["counts"] == before

    after = runs.count_run_rows(run_id, db_path=isolated_db)
    assert all(count == 0 for count in after.values()), after
    assert not runs.run_exists(run_id)
    assert client.get(f"/api/runs/{run_id}").status_code == 404


def test_delete_removes_the_runs_persisted_log_rows(
    isolated_db: str,
) -> None:
    # Logs have no run foreign key; explicit deletion must scrub research goals
    # beyond cascading tables.
    client = make_client()
    created = _create_run(
        client, "deletion cascade probe", headers=_DELETION_OWNER
    )
    run_id = created.json()["id"]

    append_log_row(
        isolated_db,
        "Supervisor analyzing research goal: deletion cascade probe",
        run_id=run_id,
    )
    append_log_row(
        isolated_db,
        "report research_goal=deletion cascade probe run_mode=standard",
        run_id=run_id,
    )
    other_run = _create_run(
        client, "a different tenant's goal", headers=_DELETION_OTHER
    ).json()["id"]
    other_row_id = append_log_row(
        isolated_db, "other tenant's line", run_id=other_run
    )
    app_wide_row_id = append_log_row(isolated_db, "app-wide line")

    assert logs.count_logs_for_run(run_id, db_path=isolated_db) == 2

    response = client.delete(f"/api/runs/{run_id}", headers=_DELETION_OWNER)
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["app_logs"] == 2

    assert logs.count_logs_for_run(run_id, db_path=isolated_db) == 0
    remaining = logs.list_logs(db_path=isolated_db)
    assert "deletion cascade probe" not in " ".join(
        row["message"] for row in remaining
    )
    remaining_ids = {row["id"] for row in remaining}
    assert other_row_id in remaining_ids
    assert app_wide_row_id in remaining_ids


def test_delete_clears_but_does_not_remove_a_carried_document(
    isolated_db: str,
) -> None:
    # Staged documents predate runs; run deletion clears their link without
    # destroying the only uploaded copy.
    client = make_client()
    staged = client.post(
        "/api/documents",
        headers=_DELETION_OWNER,
        files={
            "file": ("notes.txt", io.BytesIO(b"private notes"), "text/plain")
        },
        data={"consent": "true"},
    )
    document_id = staged.json()["id"]
    created = _create_run(
        client,
        "Carries a document",
        headers=_DELETION_OWNER,
        document_ids=[document_id],
    )
    run_id = created.json()["id"]
    client.post(f"/api/runs/{run_id}/cancel", headers=_DELETION_OWNER)

    response = client.delete(f"/api/runs/{run_id}", headers=_DELETION_OWNER)
    assert response.status_code == 200, response.text

    remaining = documents.get_staged_documents([document_id], "delete-owner")
    assert len(remaining) == 1
    assert remaining[0]["run_id"] is None


_TIERS = ("express", "standard", "extended", "ultra")


def _tier_budget(tier: str) -> Budget:
    cfg = run_modes.resolved_run_config({"tier": tier})
    kwargs = _generator_kwargs(cfg, "offline/test", None, None)
    return Budget(
        max_iterations=int(kwargs["max_iterations"]),
        **kwargs["options"].budget,
    )


def _steady_state_coverage(cfg: dict[str, int]) -> float:
    return (
        2.0
        * cfg["tournament_pairs"]
        * cfg["max_iterations"]
        / (cfg["initial_hypotheses_count"])
    )


def _worked_stats(cfg: dict[str, int]) -> SchedulerStats:
    pool = cfg["initial_hypotheses_count"] + (
        cfg["evolution_max_count"] * cfg["max_iterations"]
    )
    return SchedulerStats(
        pool_size=pool,
        reviewed_count=pool,
        unreviewed_count=0,
        rankable_count=cfg["initial_hypotheses_count"],
        match_coverage=_steady_state_coverage(cfg),
        total_matches=2 * cfg["tournament_pairs"] * cfg["max_iterations"],
        iteration=0,
    )


@pytest.mark.parametrize("tier", _TIERS)
def test_tier_ceilings_sit_above_steady_state_and_spare_the_first_tournament(
    tier: str,
) -> None:
    # Ceilings fire on equality; values at configured steady state stop runs
    # prematurely.
    cfg = run_modes.RUN_TIER_DEFAULTS[tier]
    budget = _tier_budget(tier)
    assert budget.max_matches_per_idea is not None
    assert budget.max_matches_per_idea > _steady_state_coverage(cfg)
    assert budget.max_ideas is not None
    assert budget.max_ideas > cfg["initial_hypotheses_count"] + (
        cfg["evolution_max_count"] * cfg["max_iterations"]
    )

    decision = decide_next_task(_worked_stats(cfg), budget)

    assert decision.termination_reason not in {
        TerminationReason.MAX_MATCHES_PER_IDEA,
        TerminationReason.MAX_IDEAS,
    }
    assert decision.next_task is not TaskType.TERMINATE


_RENAME_OWNER = {"X-Client-ID": "rename-owner"}

_TITLE = "Sequential Senolytic Conditioning for Cryogenic Biostasis"


def _draft_run(
    client: TestClient, goal: str = "Extend healthy lifespan"
) -> str:
    created = _create_run(client, goal, headers=_RENAME_OWNER, tier="express")
    assert created.status_code == 200, created.text
    return str(created.json()["id"])


def test_renaming_a_run_persists_the_cleaned_title() -> None:
    client = make_client()
    run_id = _draft_run(client)

    body = client.patch(
        f"/api/runs/{run_id}",
        headers=_RENAME_OWNER,
        json={"title": f"  {_TITLE}\n"},
    ).json()

    assert body["title"] == _TITLE
    assert body["research_goal"] == "Extend healthy lifespan"
    fetched = client.get(f"/api/runs/{run_id}", headers=_RENAME_OWNER).json()
    assert fetched["title"] == _TITLE
    listed = client.get("/api/runs", headers=_RENAME_OWNER).json()["runs"]
    assert [r["title"] for r in listed if r["id"] == run_id] == [_TITLE]


@pytest.mark.parametrize("title", ["", "   ", "x" * 81])
def test_blank_and_overlong_titles_are_refused(title: str) -> None:
    client = make_client()
    run_id = _draft_run(client)

    response = client.patch(
        f"/api/runs/{run_id}", headers=_RENAME_OWNER, json={"title": title}
    )

    assert response.status_code == 422


def test_rename_and_delete_refuse_foreign_demo_and_unknown_runs() -> None:
    client = make_client()
    run_id = _draft_run(client)
    stranger = {"X-Client-ID": "someone-else"}
    demo = seed_run("Demo goal", client_id=DEMO_CLIENT_ID)
    runs.update_run_status(demo.id, RunStatus.COMPLETED)

    def refused(method: str, run: str, headers: dict[str, str]) -> int:
        return client.request(
            method, f"/api/runs/{run}", headers=headers, json={"title": _TITLE}
        ).status_code

    assert refused("PATCH", run_id, stranger) == 404
    assert refused("DELETE", run_id, stranger) == 404
    assert refused("PATCH", "no-such-run", _RENAME_OWNER) == 404
    assert refused("DELETE", "no-such-run", _RENAME_OWNER) == 404
    assert refused("PATCH", demo.id, _RENAME_OWNER) == 403
    assert refused("DELETE", demo.id, _RENAME_OWNER) == 403
    runs.update_run_status(run_id, RunStatus.RUNNING)
    assert refused("DELETE", run_id, _RENAME_OWNER) == 409
    run = runs.get_run(run_id)
    assert run is not None and run.title != _TITLE


@pytest.mark.parametrize(
    ("section", "stored", "shown"),
    [
        ("attributes", ["Mechanistically specific"], None),
        (
            "attributes",
            [{"name": "Mechanism Novelty", "scale": {"1": "Low", "5": "High"}}],
            "Mechanism Novelty: 1-5 scale (1: Low, 5: High)",
        ),
        (
            "attributes",
            [{"name": "Target Area", "values": ["A", "B", "C"]}],
            "Target Area (A, B, or C)",
        ),
        ("criteria", ["Scientific soundness"], None),
        (
            "criteria",
            [{"name": "Idea correctness", "value": "Required"}],
            "Idea correctness: Required",
        ),
    ],
)
def test_setup_lists_render_every_stored_shape(
    section: str, stored: list[Any], shown: str | None
) -> None:
    display = getattr(
        run_modes,
        "attribute_display_strings"
        if section == "attributes"
        else "criteria_display_strings",
    )
    expected = [shown or stored[0]]
    assert display(stored) == expected
    assert display(None) == []
    guidance = run_modes.setup_guidance(
        {section: stored, "focus": "balance", "tier": "standard"}
    )
    assert f"- {section.title()}:\n  - {expected[0]}" in guidance
