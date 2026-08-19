"""Creating a computational-discovery run over the API.

Before this, `config["discovery"]` could only be written straight into
the store, which meant the whole discovery product -- sandbox, proposal
agent, archive, report -- was complete and unreachable from outside
Python. Two rules are pinned here. The spec has to survive run creation
verbatim, because the override path coerces unknown keys to numbers and
would drop a dict without a word. And a malformed spec has to fail the
request, because every later read of it raises: deferred, it becomes
hundreds of identically-failing evaluations instead of one 422.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests._client import make_client as _client


def _spec(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "objective": {"metric": "score", "direction": "maximize"},
        "stages": [
            {
                "name": "run",
                "argv": [sys.executable, "main.py"],
                "timeout_seconds": 60,
            }
        ],
        "seed_source": {"main.py": "print('hi')\n"},
    }
    spec.update(overrides)
    return spec


@pytest.fixture
def client(isolated_db: str) -> Any:
    with _client() as client:
        yield client


def test_a_discovery_spec_survives_run_creation(client: TestClient) -> None:
    created = client.post(
        "/api/runs",
        json={"research_goal": "beat the baseline", "discovery": _spec()},
    )
    assert created.status_code == 200
    run = client.get(f"/api/runs/{created.json()['id']}").json()
    assert run["config"]["discovery"] == _spec()


def test_a_run_without_one_is_untouched(client: TestClient) -> None:
    created = client.post("/api/runs", json={"research_goal": "cure things"})
    run = client.get(f"/api/runs/{created.json()['id']}").json()
    assert "discovery" not in run["config"]


@pytest.mark.parametrize(
    ("spec", "reason"),
    [
        ({"objective": {"metric": "score"}}, "no stages"),
        (_spec(stages=[]), "empty stages"),
        (
            _spec(objective={"metric": "s", "direction": "sideways"}),
            "direction",
        ),
        (_spec(seed_source={}), "no seed"),
        (_spec(grid={"strategy": "invented"}), "unknown strategy"),
        (
            _spec(
                grid={"strategy": "fixed"},
                descriptors=[{"feature": "ast_shape", "bins": [0.5]}],
            ),
            "a vector axis a fixed grid can never bin",
        ),
    ],
)
def test_a_malformed_spec_is_refused_at_creation(
    client: TestClient, spec: dict[str, Any], reason: str
) -> None:
    created = client.post(
        "/api/runs",
        json={"research_goal": "beat the baseline", "discovery": spec},
    )
    assert created.status_code == 422, reason
    assert "discovery spec" in created.json()["detail"]


@pytest.mark.asyncio
async def test_an_api_created_run_reaches_the_discovery_loop(
    client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The point of the endpoint. Asserting the config key alone would
    # pass even if bootstrap ignored it and ran the hypothesis graph.
    from app import engine_tasks, store

    monkeypatch.setenv("COSCIENTIST_WORKSPACE_DIR", str(tmp_path / "ws"))
    created = client.post(
        "/api/runs",
        json={
            "research_goal": "beat the baseline",
            "discovery": _spec(max_generations=1),
        },
    ).json()
    engine_tasks.enqueue_bootstrap(created["id"])
    for _ in range(40):
        task = store.claim_task("test-worker", run_id=created["id"])
        if task is None:
            break
        store.complete_task(
            task.id, "test-worker", await engine_tasks.execute_engine_task(task)
        )

    variants = store.list_code_variants(created["id"])
    assert [v["source"] for v in variants] == [_spec()["seed_source"]]
    assert store.get_run(created["id"]).status == "completed"
    assert (
        store.get_latest_report(created["id"])["payload"]["report_kind"]
        == "discovery"
    )
