"""Run-create request receipts at the owned HTTP boundary."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest

from app import credentials
from app.config import settings
from tests._client import make_client

_OWNER = "idempotency-owner"
_KEY = "run-create-01"
_PAYLOAD = {
    "research_goal": "Study a defined signaling pathway",
    "tier": "express",
}


def _post_run(
    client: Any,
    *,
    owner: str = _OWNER,
    request_key: str | None = _KEY,
    payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    headers = {"X-Client-ID": owner}
    if request_key is not None:
        headers["Idempotency-Key"] = request_key
    headers.update(extra_headers or {})
    return client.post("/api/runs", json=payload or _PAYLOAD, headers=headers)


def _owned_run_ids(client: Any, owner: str = _OWNER) -> list[str]:
    response = client.get("/api/runs", headers={"X-Client-ID": owner})
    assert response.status_code == 200, response.text
    return [run["id"] for run in response.json()["runs"]]


def test_exact_retry_returns_the_original_run() -> None:
    client = make_client()
    first = _post_run(client)
    retry = _post_run(client)

    assert first.status_code == retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]
    assert _owned_run_ids(client) == [first.json()["id"]]


def test_changed_request_with_the_same_key_conflicts() -> None:
    client = make_client()
    first = _post_run(client)
    changed = _post_run(
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
    client = make_client()
    first = _post_run(client, owner="owner-one")
    second = _post_run(client, owner="owner-two")

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert _owned_run_ids(client, "owner-one") == [first.json()["id"]]
    assert _owned_run_ids(client, "owner-two") == [second.json()["id"]]


def test_idempotency_key_values_are_case_sensitive() -> None:
    client = make_client()
    upper = _post_run(client, request_key="Run-A")
    lower = _post_run(client, request_key="run-a")

    assert upper.status_code == lower.status_code == 200
    assert upper.json()["id"] != lower.json()["id"]
    assert len(_owned_run_ids(client)) == 2


def test_unkeyed_legacy_calls_still_create_distinct_runs() -> None:
    client = make_client()
    first = _post_run(client, request_key=None)
    second = _post_run(client, request_key=None)

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert set(_owned_run_ids(client)) == {
        first.json()["id"],
        second.json()["id"],
    }


def test_concurrent_exact_retries_create_one_run() -> None:
    client = make_client()
    start_together = Barrier(2)

    def submit() -> Any:
        start_together.wait(timeout=5)
        return _post_run(client)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [
            future.result(timeout=10)
            for future in (pool.submit(submit), pool.submit(submit))
        ]

    assert [response.status_code for response in responses] == [200, 200]
    run_ids = {response.json()["id"] for response in responses}
    assert len(run_ids) == 1
    assert _owned_run_ids(client) == list(run_ids)


def test_malformed_idempotency_key_is_rejected() -> None:
    client = make_client()
    response = _post_run(client, request_key="contains spaces")

    assert response.status_code == 400
    assert _owned_run_ids(client) == []


def test_changed_byok_key_conflicts_without_echoing_either_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings, "byok_encryption_key", "test-encryption-secret"
    )

    async def accept_credential(
        _credential: credentials.ByokCredential,
    ) -> None:
        return None

    async def no_model_call(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        credentials, "validate_byok_credential", accept_credential
    )
    monkeypatch.setattr("app.runs_crud.generate_run_title", no_model_call)
    monkeypatch.setattr(
        "app.runs_crud.generate_goal_restatement", no_model_call
    )

    client = make_client()
    first_secret = "sk-first-private-value"
    changed_secret = "sk-changed-private-value"
    byok_headers = {"X-LLM-Provider": "deepseek"}
    first = _post_run(
        client,
        extra_headers={**byok_headers, "X-LLM-API-Key": first_secret},
    )
    changed = _post_run(
        client,
        extra_headers={**byok_headers, "X-LLM-API-Key": changed_secret},
    )

    assert first.status_code == 200
    assert changed.status_code == 409
    assert first_secret not in changed.text
    assert changed_secret not in changed.text
    assert _owned_run_ids(client) == [first.json()["id"]]
