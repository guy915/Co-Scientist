"""The variant endpoints, including who is allowed to read them."""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import store
from tests._client import make_client


@pytest.fixture
def db(isolated_db: str) -> str:
    return os.environ["COSCIENTIST_DB_PATH"]


@pytest.fixture
def client(db: str) -> TestClient:
    return make_client()


def _run_with_variants(client: TestClient) -> tuple[str, list[str]]:
    """Creates a run owned by the test client, with three variants."""
    created = client.post(
        "/api/runs", json={"research_goal": "discovery", "mode": "standard"}
    )
    run_id = str(created.json()["id"])
    ids = []
    for index, fitness in enumerate((1.0, None, 5.0)):
        variant_id = store.add_code_variant(
            store.NewCodeVariant(
                run_id=run_id,
                source={"main.py": f"x = {index}"},
                operator="targeted_edit" if index else None,
            )
        )
        store.record_variant_evaluation(
            variant_id,
            store.VariantEvaluation(
                status="ok" if fitness is not None else "failed",
                fitness=fitness,
                metrics={"score": fitness} if fitness is not None else {},
                artifacts={} if fitness is not None else {"stderr": "boom"},
            ),
        )
        ids.append(variant_id)
    return run_id, ids


def test_variants_are_listed_in_attempt_order(client: TestClient) -> None:
    run_id, ids = _run_with_variants(client)
    body = client.get(f"/api/runs/{run_id}/variants").json()
    assert [v["id"] for v in body["variants"]] == ids
    assert [v["ordinal"] for v in body["variants"]] == [1, 2, 3]


def test_a_failed_variant_keeps_its_place_in_the_list(
    client: TestClient,
) -> None:
    run_id, _ = _run_with_variants(client)
    body = client.get(f"/api/runs/{run_id}/variants").json()
    assert [v["fitness"] for v in body["variants"]] == [1.0, None, 5.0]


def test_the_detail_view_carries_metrics_and_artifacts(
    client: TestClient,
) -> None:
    run_id, ids = _run_with_variants(client)
    body = client.get(f"/api/runs/{run_id}/variants/{ids[1]}").json()
    assert body["artifacts"] == {"stderr": "boom"}
    assert body["source"] == {"main.py": "x = 1"}


def test_a_variant_from_another_run_is_not_readable(
    client: TestClient,
) -> None:
    # Ownership is enforced on the run, so a variant id must not be a way
    # to reach across runs.
    _, ids = _run_with_variants(client)
    other = client.post(
        "/api/runs", json={"research_goal": "other", "mode": "standard"}
    ).json()["id"]
    assert client.get(f"/api/runs/{other}/variants/{ids[0]}").status_code == 404


def test_variants_of_an_unowned_run_are_not_readable(
    client: TestClient,
) -> None:
    run_id, _ = _run_with_variants(client)
    stranger: dict[str, Any] = {"X-Client-ID": "someone-else"}
    response = client.get(f"/api/runs/{run_id}/variants", headers=stranger)
    assert response.status_code == 404


def test_a_run_with_no_variants_returns_an_empty_list(
    client: TestClient,
) -> None:
    run_id = client.post(
        "/api/runs", json={"research_goal": "empty", "mode": "standard"}
    ).json()["id"]
    assert client.get(f"/api/runs/{run_id}/variants").json() == {"variants": []}
