"""Run setup's attached-document writes commit with the creation receipt."""

from __future__ import annotations

import io
from typing import Any

import pytest

from app import credentials, store
from app.config import settings
from app.store import receipts as store_receipts
from tests._client import make_client

_OWNER = "run-rollback-owner"
_KEY = "rollback-run-01"


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
        headers={"X-Client-ID": _OWNER},
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
        "X-Client-ID": _OWNER,
        "Idempotency-Key": _KEY,
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
        client.get("/api/runs", headers={"X-Client-ID": _OWNER}).json()["runs"]
        == []
    )
    document = store.get_staged_documents([document_id], _OWNER)[0]
    assert document["run_id"] is None
    with store.connect() as conn:
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
        store.get_staged_documents([document_id], _OWNER)[0]["run_id"]
        == (retried.json()["id"])
    )
    with store.connect() as conn:
        digest = conn.execute(
            "SELECT request_digest FROM run_creation_receipts WHERE run_id=?",
            (retried.json()["id"],),
        ).fetchone()[0]
    assert provider_key not in digest
