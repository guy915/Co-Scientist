from __future__ import annotations

import asyncio
import hashlib
import io
import pathlib
import re
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
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
    RESEARCH_OVERVIEW_MIN_LLM_CALLS,
    decide_next_task,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.run_modes as run_modes_attributes_mod
import app.run_modes as run_modes_criteria
from app import async_bridge, credentials, engine_tasks, run_modes, task_worker
from app.config import settings
from app.engine_adapter.opts import _generator_kwargs
from app.run_modes import RUN_TIER_DEFAULTS
from app.runs import crud as runs_crud
from app.store import db, documents, logs, runs, tasks
from app.store import receipts as store_receipts
from app.store.models import DEMO_CLIENT_ID, RunStatus, ScientificTask
from app.store.runs import RunCreateOptions
from app.store.schema import SCHEMA
from tests._client import append_log_row, wait_for
from tests._client import create_run as _create_run
from tests._client import make_client as _deletion_make_client
from tests._client import make_client as _idempotency_make_client
from tests._client import make_client as _migration_make_client
from tests._client import make_client as _rollback_make_client
from tests._store_helpers import enqueue_task, seed_run

from ._client import make_client as _rename_make_client
from ._llm_fake_backend import install_completion_backend


@pytest.mark.parametrize("mode", ["blocked_paid", "campaign_free", "user_byok"])
@pytest.mark.parametrize("recovered", [False, True])
@pytest.mark.parametrize("auxiliary", ["claim", "batch", "safety"])
async def test_durable_auxiliary_admission_with_stored_credential(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    recovered: bool,
    auxiliary: str,
    mode: str,
) -> None:
    from co_scientist.llm.admission import free_policy as free_catalog

    import app.claims.verifier as claim_verifier_batch
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
        "batch": partial(
            claim_verifier_batch._call_claim_json_async,
            "deployment",
            claim_verifier_batch._EntailmentRequest(
                lambda: claim_verifier_batch._batch_entailment_prompt(
                    ["claim"], []
                ),
                claim_verifier_batch._BATCH_DRAFT_SCHEMA,
                claim_verifier_batch._BATCH_MAX_TOKENS,
                "claim_verifier_batch",
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


def test_exact_retry_returns_the_original_run() -> None:
    client = _idempotency_make_client()
    first = _idempotency_post_run(client)
    retry = _idempotency_post_run(client)

    assert first.status_code == retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]
    assert _owned_run_ids(client) == [first.json()["id"]]


def test_changed_request_with_the_same_key_conflicts() -> None:
    client = _idempotency_make_client()
    first = _idempotency_post_run(client)
    changed = _idempotency_post_run(
        client,
        payload={
            "research_goal": "Study a different signaling pathway",
            "tier": "express",
        },
    )

    assert first.status_code == 200
    assert changed.status_code == 409
    assert _owned_run_ids(client) == [first.json()["id"]]


def test_the_same_key_is_independent_between_owners() -> None:
    client = _idempotency_make_client()
    first = _idempotency_post_run(client, owner="owner-one")
    second = _idempotency_post_run(client, owner="owner-two")

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert _owned_run_ids(client, "owner-one") == [first.json()["id"]]
    assert _owned_run_ids(client, "owner-two") == [second.json()["id"]]


def test_idempotency_key_values_are_case_sensitive() -> None:
    client = _idempotency_make_client()
    upper = _idempotency_post_run(client, request_key="Run-A")
    lower = _idempotency_post_run(client, request_key="run-a")

    assert upper.status_code == lower.status_code == 200
    assert upper.json()["id"] != lower.json()["id"]
    assert len(_owned_run_ids(client)) == 2


def test_unkeyed_legacy_calls_still_create_distinct_runs() -> None:
    client = _idempotency_make_client()
    first = _idempotency_post_run(client, request_key=None)
    second = _idempotency_post_run(client, request_key=None)

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert set(_owned_run_ids(client)) == {
        first.json()["id"],
        second.json()["id"],
    }


def test_concurrent_exact_retries_create_one_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _idempotency_make_client()
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
    client = _idempotency_make_client()
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

    client = _idempotency_make_client()
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


def test_create_route_uses_the_runs_crud_byok_monkeypatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject_byok(*_args: Any, **_kwargs: Any) -> None:
        raise HTTPException(status_code=418, detail="patched resolver")

    monkeypatch.setattr(runs_crud, "_resolve_byok", reject_byok)
    client = _idempotency_make_client()

    response = _idempotency_post_run(client)

    assert response.status_code == 418
    assert response.json()["detail"] == "patched resolver"
    assert _owned_run_ids(client) == []


def test_create_route_uses_one_patched_client_scope_for_run_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_checks: list[str] = []
    policy_scopes: list[str] = []

    def require_scope(_request: Any) -> str:
        scope_checks.append("checked")
        return "patched-owner-scope"

    def execution_policy(_request: Any, _interview: Any) -> str:
        return "campaign"

    @contextmanager
    def scoped_policy(policy: str) -> Iterator[None]:
        policy_scopes.append(policy)
        yield

    monkeypatch.setattr(runs_crud, "require_client_scope", require_scope)
    monkeypatch.setattr(
        runs_crud, "client_id", lambda _request: "patched-owner-scope"
    )
    monkeypatch.setattr(runs_crud, "resolve_execution_policy", execution_policy)
    monkeypatch.setattr(runs_crud, "scoped_execution_policy", scoped_policy)
    client = _idempotency_make_client()

    response = _idempotency_post_run(client)

    assert response.status_code == 200
    run = runs.get_run(response.json()["id"])
    assert run is not None
    assert run.client_id == "patched-owner-scope"
    assert run.execution_policy == "campaign"
    assert scope_checks == ["checked"]
    assert policy_scopes == ["campaign"]


_MIGRATION_PAYLOAD = {
    "research_goal": "Study a defined signaling pathway",
    "tier": "express",
}


def _migration_post_run(
    client: TestClient,
    owner: str,
    key: str | None,
    payload: dict[str, Any] | None = None,
) -> Any:
    headers = {"X-Client-ID": owner}
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(
        "/api/runs",
        headers=headers,
        json=payload if payload is not None else _MIGRATION_PAYLOAD,
    )


def test_post_run_preserves_existing_data_and_persists_receipts(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy_run_id = "pre-receipt-run"
    raw = sqlite3.connect(isolated_db)
    try:
        raw.executescript(SCHEMA)
        raw.executescript(
            """
            INSERT INTO runs (
                id, research_goal, profile, status, provider, config_json,
                client_id, created_at, updated_at, llm_backend
            ) VALUES (
                'pre-receipt-run', 'Persisted before receipt support',
                'standard', 'completed', 'engine', '{}',
                'legacy-owner', 1, 1, 'offline'
            );
            INSERT INTO run_events (
                run_id, seq, type, payload_json, created_at
            ) VALUES (
                'pre-receipt-run', 1, 'lifecycle', '{"event":"created"}', 1
            );
            """
        )
        raw.commit()
    finally:
        raw.close()

    client = _migration_make_client()
    created = _migration_post_run(client, "new-owner", "after-upgrade")

    assert created.status_code == 200, created.text
    assert _migration_post_run(client, "new-owner", "after-upgrade").json() == (
        created.json()
    )
    owned = client.get("/api/runs", headers={"X-Client-ID": "legacy-owner"})
    assert owned.status_code == 200, owned.text
    assert [run["id"] for run in owned.json()["runs"]] == [legacy_run_id]

    with sqlite3.connect(isolated_db) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "run_creation_receipts" in tables
        assert (
            conn.execute(
                "SELECT payload_json FROM run_events WHERE run_id=? AND seq=1",
                (legacy_run_id,),
            ).fetchone()[0]
            == '{"event":"created"}'
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM runs WHERE id IN (?, ?)",
                (legacy_run_id, created.json()["id"]),
            ).fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "SELECT run_id FROM run_creation_receipts "
                "WHERE client_id=? AND idempotency_key=?",
                ("new-owner", "after-upgrade"),
            ).fetchone()[0]
            == created.json()["id"]
        )

    document_bytes = b"ERK1 phosphorylation supports tissue repair.\n"
    staged = client.post(
        "/api/documents",
        headers={"X-Client-ID": "new-owner"},
        files={
            "file": ("lab-notes.txt", io.BytesIO(document_bytes), "text/plain")
        },
        data={"consent": "true"},
    )
    assert staged.status_code == 200, staged.text
    document = staged.json()
    digest = hashlib.sha256(document_bytes).hexdigest()
    assert document["sha256"] == digest

    api_key = "sk-receipt-private-value"
    validated: list[str] = []
    mocked_background: list[str] = []

    async def accept_byok(credential: credentials.ByokCredential) -> None:
        validated.append(credential.api_key)

    async def mock_title(*_args: Any, **_kwargs: Any) -> None:
        mocked_background.append("title")

    async def mock_restatement(*_args: Any, **_kwargs: Any) -> None:
        mocked_background.append("restatement")

    monkeypatch.setattr(settings, "byok_encryption_key", "receipt-test-key")
    monkeypatch.setattr(credentials, "validate_byok_credential", accept_byok)
    monkeypatch.setattr("app.runs.crud.generate_run_title", mock_title)
    monkeypatch.setattr(
        "app.runs.crud.generate_goal_restatement", mock_restatement
    )

    byok_payload = {**_MIGRATION_PAYLOAD, "document_ids": [document["id"]]}
    byok_headers = {
        "X-Client-ID": "new-owner",
        "Idempotency-Key": "byok-with-document",
        credentials.PROVIDER_HEADER: "deepseek",
        credentials.API_KEY_HEADER: api_key,
    }
    byok_run = client.post("/api/runs", headers=byok_headers, json=byok_payload)
    assert byok_run.status_code == 200, byok_run.text
    assert api_key not in byok_run.text

    run_id = byok_run.json()["id"]
    evidence_response = client.get(
        f"/api/runs/{run_id}/evidence", headers={"X-Client-ID": "new-owner"}
    )
    assert evidence_response.status_code == 200, evidence_response.text
    evidence = evidence_response.json()["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["title"] == "lab-notes.txt"
    assert evidence[0]["abstract"] == document_bytes.decode()
    assert evidence[0]["source"] == "attachment"
    assert evidence[0]["sha256"] == digest
    assert evidence[0]["document_version"] == digest
    assert evidence[0]["extraction_tool"] == "utf8-decoder-v1"
    assert evidence[0]["mime_type"] == "text/plain"
    assert evidence[0]["byte_size"] == len(document_bytes)

    replay = client.post("/api/runs", headers=byok_headers, json=byok_payload)
    assert replay.status_code == 200, replay.text
    assert replay.json() == byok_run.json()
    assert api_key not in replay.text
    evidence_after_replay = client.get(
        f"/api/runs/{run_id}/evidence", headers={"X-Client-ID": "new-owner"}
    ).json()["evidence"]
    assert evidence_after_replay == evidence
    assert validated == [api_key]
    assert mocked_background == ["title", "restatement"]

    stored_credential = credentials.get_run_credential(
        run_id, db_path=isolated_db
    )
    assert stored_credential is not None
    assert stored_credential.api_key == api_key
    assert stored_credential.provider == "deepseek"
    with sqlite3.connect(isolated_db) as conn:
        encrypted_key = conn.execute(
            "SELECT encrypted_key FROM run_credentials WHERE run_id=?",
            (run_id,),
        ).fetchone()[0]
        receipt_digest = conn.execute(
            "SELECT request_digest FROM run_creation_receipts "
            "WHERE client_id=? AND idempotency_key=?",
            ("new-owner", "byok-with-document"),
        ).fetchone()[0]
        assert api_key not in encrypted_key
        assert api_key not in receipt_digest
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM runs WHERE client_id=?", ("new-owner",)
            ).fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM run_credentials WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM evidence WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM run_creation_receipts "
                "WHERE client_id=? AND idempotency_key=?",
                ("new-owner", "byok-with-document"),
            ).fetchone()[0]
            == 1
        )

    legacy_first = _migration_post_run(client, "new-owner", None)
    legacy_second = _migration_post_run(client, "new-owner", None)
    assert legacy_first.status_code == legacy_second.status_code == 200
    assert legacy_first.json()["id"] != legacy_second.json()["id"]


def test_concurrent_changed_payloads_commit_one_same_key_run(
    isolated_db: str,
) -> None:
    client = _migration_make_client()
    owner = "changed-race-owner"
    key = "changed-payload-race"
    payloads = (
        _MIGRATION_PAYLOAD,
        {**_MIGRATION_PAYLOAD, "research_goal": "Study a different pathway"},
    )
    start_together = Barrier(len(payloads))

    def submit(payload: dict[str, Any]) -> Any:
        start_together.wait(timeout=5)
        return _migration_post_run(client, owner, key, payload)

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


def test_concurrent_same_key_requests_are_isolated_by_owner() -> None:
    client = _migration_make_client()
    owners = ("owner-one", "owner-two")
    start_together = Barrier(len(owners))

    def submit(owner: str) -> tuple[str, Any]:
        start_together.wait(timeout=5)
        return owner, _migration_post_run(client, owner, "shared-key")

    with ThreadPoolExecutor(max_workers=len(owners)) as pool:
        futures = [pool.submit(submit, owner) for owner in owners]
        responses = [future.result(timeout=10) for future in futures]

    run_payloads: dict[str, dict[str, Any]] = {}
    for owner, response in responses:
        assert response.status_code == 200, response.text
        run_payloads[owner] = response.json()
    assert run_payloads["owner-one"]["id"] != run_payloads["owner-two"]["id"]

    for owner in owners:
        replay = _migration_post_run(client, owner, "shared-key")
        assert replay.status_code == 200, replay.text
        assert replay.json() == run_payloads[owner]
        listed = client.get("/api/runs", headers={"X-Client-ID": owner})
        assert [run["id"] for run in listed.json()["runs"]] == [
            run_payloads[owner]["id"]
        ]

    hidden_from_other_owner = client.get(
        f"/api/runs/{run_payloads['owner-two']['id']}",
        headers={"X-Client-ID": "owner-one"},
    )
    assert hidden_from_other_owner.status_code == 404


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
    client = _rollback_make_client()
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


def test_delete_requires_a_terminal_run() -> None:
    # Set RUNNING directly so a fast offline completion cannot race the delete
    # guard.
    client = _deletion_make_client()
    created = _create_run(client, "Active run goal", headers=_DELETION_OWNER)
    run_id = created.json()["id"]
    runs.update_run_status(run_id, RunStatus.RUNNING)

    response = client.delete(f"/api/runs/{run_id}", headers=_DELETION_OWNER)

    assert response.status_code == 409
    assert runs.run_exists(run_id)


def test_delete_unknown_run_404s() -> None:
    client = _deletion_make_client()
    response = client.delete(
        "/api/runs/does-not-exist", headers=_DELETION_OWNER
    )
    assert response.status_code == 404


def test_another_client_cannot_delete_the_run() -> None:
    client = _deletion_make_client()
    created = _create_run(client, "Owned goal", headers=_DELETION_OWNER)
    run_id = created.json()["id"]

    response = client.delete(f"/api/runs/{run_id}", headers=_DELETION_OTHER)

    assert response.status_code == 404
    assert runs.run_exists(run_id)


def test_demo_run_cannot_be_deleted() -> None:
    client = _deletion_make_client()
    demo = seed_run("Demo goal", client_id=DEMO_CLIENT_ID)
    runs.update_run_status(demo.id, RunStatus.COMPLETED)

    response = client.delete(f"/api/runs/{demo.id}", headers=_DELETION_OWNER)

    assert response.status_code == 403
    assert runs.run_exists(demo.id)


def test_delete_cascades_across_every_run_scoped_table(
    isolated_db: str,
) -> None:
    client = _deletion_make_client()
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
    client = _deletion_make_client()
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
    client = _deletion_make_client()
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


def test_every_tier_caps_its_llm_call_spend() -> None:
    # Maintenance loops do not advance iterations; every tier still needs a
    # provider-call ceiling.
    ceilings = {
        tier: cfg["max_llm_calls"]
        for tier, cfg in run_modes.RUN_TIER_DEFAULTS.items()
    }
    assert all(value > 0 for value in ceilings.values())
    ordered = ["express", "standard", "extended", "ultra"]
    assert [ceilings[tier] for tier in ordered] == sorted(
        ceilings[tier] for tier in ordered
    )


def test_resolved_config_carries_the_tier_call_ceiling() -> None:
    config = run_modes.resolved_run_config({"tier": "express"})
    assert (
        config["max_llm_calls"]
        == (run_modes.RUN_TIER_DEFAULTS["express"]["max_llm_calls"])
    )


def test_default_attributes_are_goal_agnostic_scaled_axes() -> None:
    for attribute in run_modes_attributes_mod.DEFAULT_ATTRIBUTES:
        assert set(attribute) == {"name", "scale"}
        assert attribute["name"]
        assert set(attribute["scale"]) == {"1", "3", "5"}
        assert all(attribute["scale"].values())


def test_setup_config_defaults_attributes_to_independent_copies() -> None:
    first = run_modes.setup_config(research_goal="goal one")
    second = run_modes.setup_config(research_goal="goal two")
    assert first["attributes"] == list(
        run_modes_attributes_mod.DEFAULT_ATTRIBUTES
    )
    first["attributes"][0]["scale"]["1"] = "mutated"
    assert second["attributes"][0]["scale"]["1"] != "mutated"


def test_setup_config_keeps_accepting_legacy_free_string_attributes() -> None:
    spec = run_modes.setup_config(
        research_goal="goal",
        lists=run_modes.PlanningLists(attributes=["Spatially resolved", ""]),
    )
    assert spec["attributes"] == ["Spatially resolved"]


def test_setup_config_keeps_accepting_a_categorical_attribute() -> None:
    spec = run_modes.setup_config(
        research_goal="goal",
        lists=run_modes.PlanningLists(
            attributes=[
                {
                    "name": "Target Area",
                    "values": ["Epigenetics", "Stromal-Immune Crosstalk"],
                }
            ]
        ),
    )
    assert spec["attributes"] == [
        {
            "name": "Target Area",
            "values": ["Epigenetics", "Stromal-Immune Crosstalk"],
        }
    ]


def test_attribute_display_strings_renders_every_stored_shape() -> None:
    assert run_modes.attribute_display_strings(
        ["Mechanistically specific"]
    ) == ["Mechanistically specific"]
    assert run_modes.attribute_display_strings(
        [{"name": "Mechanism Novelty", "scale": {"1": "Low", "5": "High"}}]
    ) == ["Mechanism Novelty: 1-5 scale (1: Low, 5: High)"]
    assert run_modes.attribute_display_strings(
        [{"name": "Target Area", "values": ["A", "B", "C"]}]
    ) == ["Target Area (A, B, or C)"]
    assert run_modes.attribute_display_strings([{"name": "Impact"}]) == [
        "Impact"
    ]
    assert run_modes.attribute_display_strings(None) == []


def test_setup_guidance_renders_attributes_for_both_stored_shapes() -> None:
    legacy = run_modes.setup_guidance(
        {
            "attributes": ["Mechanistically specific"],
            "focus": "balance",
            "tier": "standard",
        }
    )
    assert "- Attributes:\n  - Mechanistically specific" in legacy

    current = run_modes.setup_guidance(
        run_modes.setup_config(research_goal="goal")
    )
    assert "- Attributes:\n  - Mechanistic specificity: 1-5 scale" in current


def test_default_criteria_are_named_settings_with_values() -> None:
    for pair in run_modes_criteria.DEFAULT_CRITERIA:
        assert set(pair) == {"name", "value"}
        assert pair["name"] and pair["value"]


def test_setup_config_defaults_criteria_to_independent_copies() -> None:
    first = run_modes.setup_config(research_goal="goal one")
    second = run_modes.setup_config(research_goal="goal two")
    assert first["criteria"] == list(run_modes_criteria.DEFAULT_CRITERIA)
    first["criteria"][0]["value"] = "mutated"
    assert second["criteria"][0]["value"] != "mutated"


def test_setup_config_keeps_accepting_legacy_free_string_criteria() -> None:
    spec = run_modes.setup_config(
        research_goal="goal",
        lists=run_modes.PlanningLists(criteria=["Causal specificity", ""]),
    )
    assert spec["criteria"] == ["Causal specificity"]


def test_criteria_display_strings_renders_both_stored_shapes() -> None:
    assert run_modes.criteria_display_strings(["Scientific soundness"]) == [
        "Scientific soundness"
    ]
    assert run_modes.criteria_display_strings(
        [{"name": "Idea correctness", "value": "Required"}]
    ) == ["Idea correctness: Required"]
    assert run_modes.criteria_display_strings([{"name": "Impact"}]) == [
        "Impact"
    ]
    assert run_modes.criteria_display_strings(None) == []


def test_setup_guidance_renders_criteria_for_both_stored_shapes() -> None:
    legacy = run_modes.setup_guidance(
        {
            "criteria": ["Scientific soundness"],
            "focus": "balance",
            "tier": "standard",
        }
    )
    assert "- Criteria:\n  - Scientific soundness" in legacy

    current = run_modes.setup_guidance(
        run_modes.setup_config(research_goal="goal")
    )
    assert "- Criteria:\n  - Idea correctness: Required" in current


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
def test_tier_arms_the_published_while_guard(tier: str) -> None:
    budget = _tier_budget(tier)
    assert budget.max_ideas is not None
    assert budget.max_matches_per_idea is not None


@pytest.mark.parametrize("tier", _TIERS)
def test_ceilings_sit_above_the_tier_own_steady_state(tier: str) -> None:
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


@pytest.mark.parametrize("tier", _TIERS)
def test_first_tournament_does_not_terminate_the_run(tier: str) -> None:
    cfg = run_modes.RUN_TIER_DEFAULTS[tier]
    decision = decide_next_task(_worked_stats(cfg), _tier_budget(tier))
    assert decision.termination_reason not in {
        TerminationReason.MAX_MATCHES_PER_IDEA,
        TerminationReason.MAX_IDEAS,
    }
    assert decision.next_task is not TaskType.TERMINATE


def test_periodic_overview_gate_reads_extended_and_up_only() -> None:
    # Overview cost gates must distinguish standard from extended as tier
    # budgets change.
    assert (
        run_modes.RUN_TIER_DEFAULTS["standard"]["max_llm_calls"]
        < RESEARCH_OVERVIEW_MIN_LLM_CALLS
        <= run_modes.RUN_TIER_DEFAULTS["extended"]["max_llm_calls"]
    )


_RENAME_OWNER = {"X-Client-ID": "rename-owner"}
_RENAME_OTHER = {"X-Client-ID": "someone-else"}

_TITLE = "Sequential Senolytic Conditioning for Cryogenic Biostasis"


def _draft_run(
    client: TestClient, goal: str = "Extend healthy lifespan"
) -> str:
    created = _create_run(client, goal, headers=_RENAME_OWNER, tier="express")
    assert created.status_code == 200, created.text
    return str(created.json()["id"])


def test_renames_the_run_and_returns_its_details() -> None:
    client: TestClient = _rename_make_client()
    run_id = _draft_run(client)

    response = client.patch(
        f"/api/runs/{run_id}", headers=_RENAME_OWNER, json={"title": _TITLE}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == _TITLE
    assert body["id"] == run_id
    assert "summary" in body


def test_the_new_title_is_what_later_reads_return() -> None:
    client: TestClient = _rename_make_client()
    run_id = _draft_run(client)

    client.patch(
        f"/api/runs/{run_id}", headers=_RENAME_OWNER, json={"title": _TITLE}
    )

    fetched = client.get(f"/api/runs/{run_id}", headers=_RENAME_OWNER).json()
    assert fetched["title"] == _TITLE
    listed = client.get("/api/runs", headers=_RENAME_OWNER).json()["runs"]
    assert [r["title"] for r in listed if r["id"] == run_id] == [_TITLE]


def test_the_research_goal_is_left_alone() -> None:
    client: TestClient = _rename_make_client()
    run_id = _draft_run(client, goal="Extend healthy lifespan")

    renamed = client.patch(
        f"/api/runs/{run_id}", headers=_RENAME_OWNER, json={"title": _TITLE}
    ).json()

    assert renamed["research_goal"] == "Extend healthy lifespan"


def test_surrounding_whitespace_is_collapsed() -> None:
    client: TestClient = _rename_make_client()
    run_id = _draft_run(client)

    body = client.patch(
        f"/api/runs/{run_id}",
        headers=_RENAME_OWNER,
        json={"title": "  Cryogenic   Biostasis\n"},
    ).json()

    assert body["title"] == "Cryogenic Biostasis"


def test_a_blank_title_is_refused() -> None:
    client: TestClient = _rename_make_client()
    run_id = _draft_run(client)

    empty = client.patch(
        f"/api/runs/{run_id}", headers=_RENAME_OWNER, json={"title": ""}
    )
    spaces = client.patch(
        f"/api/runs/{run_id}", headers=_RENAME_OWNER, json={"title": "   "}
    )

    assert empty.status_code == 422
    assert spaces.status_code == 422


def test_an_overlong_title_is_refused() -> None:
    client: TestClient = _rename_make_client()
    run_id = _draft_run(client)

    response = client.patch(
        f"/api/runs/{run_id}", headers=_RENAME_OWNER, json={"title": "x" * 81}
    )

    assert response.status_code == 422


def test_another_client_cannot_rename_it() -> None:
    client: TestClient = _rename_make_client()
    run_id = _draft_run(client)

    response = client.patch(
        f"/api/runs/{run_id}", headers=_RENAME_OTHER, json={"title": _TITLE}
    )

    assert response.status_code == 404
    run = runs.get_run(run_id)
    assert run is not None and run.title != _TITLE


def test_the_shared_demo_run_cannot_be_renamed() -> None:
    client: TestClient = _rename_make_client()
    demo_id = _draft_run(client)
    with db.connect() as conn:
        conn.execute(
            "UPDATE runs SET client_id=? WHERE id=?",
            (DEMO_CLIENT_ID, demo_id),
        )

    response = client.patch(
        f"/api/runs/{demo_id}", headers=_RENAME_OWNER, json={"title": _TITLE}
    )

    assert response.status_code == 403


def test_renaming_an_unknown_run_is_a_404() -> None:
    client: TestClient = _rename_make_client()

    response = client.patch(
        "/api/runs/no-such-run", headers=_RENAME_OWNER, json={"title": _TITLE}
    )

    assert response.status_code == 404
