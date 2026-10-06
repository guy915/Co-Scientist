from __future__ import annotations

import asyncio
import pathlib
import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import API_VERSION, diagnostics
from app.config import settings
from app.diagnostics import (
    HealthCheck,
    ProbeResult,
)
from app.store import checkpoints, db, runs
from app.store import runs_views as views
from app.store import tasks as store
from app.store.models import DEMO_CLIENT_ID, RunStatus
from app.store.tasks import queue_health_snapshot
from app.store.tasks_lifecycle import QueueHealthSnapshot
from tests._client import make_client as _client
from tests._client import make_operator_client
from tests._client import make_operator_client as _operator_client
from tests._store_helpers import enqueue_task, seed_checkpoint, seed_run


def test_health_ok() -> None:
    client = _client()
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "model_name" in data
    assert data["version"] == API_VERSION
    assert data["provider"] == "engine"
    assert data["checks"]["store"]["ok"] is True
    assert set(data["checks"]) == {"store", "engine", "queue", "disk"}
    assert data["checks"]["queue"]["ok"] is True
    assert data["checks"]["disk"]["ok"] is True


@pytest.mark.parametrize("operator", [True, False])
def test_health_is_unhealthy_when_the_store_is_unreachable_and_hides_detail(
    monkeypatch: pytest.MonkeyPatch, operator: bool
) -> None:
    monkeypatch.setattr(
        diagnostics,
        "check_store",
        lambda db_path=None: HealthCheck(ok=False, detail="disk on fire"),
    )

    res = (make_operator_client() if operator else _client()).get("/health")

    data = res.json()
    assert res.status_code == 503
    assert data["checks"]["store"]["ok"] is False
    if operator:
        assert data["status"] == "unhealthy"
        assert data["checks"]["store"]["detail"] == "disk on fire"
    else:
        assert data["checks"]["store"]["detail"] is None
        assert data["model_name"] is None


@pytest.mark.parametrize(
    ("has_key", "status"), [(True, "degraded"), (False, "healthy")]
)
def test_health_is_degraded_only_when_a_key_is_set_but_the_engine_is_missing(
    monkeypatch: pytest.MonkeyPatch, has_key: bool, status: str
) -> None:
    if has_key:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(
        diagnostics,
        "check_engine",
        lambda: HealthCheck(ok=False, detail="not importable"),
    )

    res = _client().get("/health")

    assert res.status_code == 200
    assert res.json()["status"] == status


def _patch_probes(
    monkeypatch: pytest.MonkeyPatch,
    mcp: ProbeResult,
    pubmed: ProbeResult,
    web_search: ProbeResult | None = None,
) -> None:
    resolved_web = web_search or ProbeResult(available=False, state="down")

    async def _stub() -> tuple[ProbeResult, ProbeResult, ProbeResult]:
        return mcp, pubmed, resolved_web

    monkeypatch.setattr(diagnostics, "_probe_literature_stack", _stub)


_INDRA_CONFIG = str(
    pathlib.Path(__file__).resolve().parents[2]
    / "engine"
    / "src"
    / "co_scientist"
    / "config"
    / "examples"
    / "indra_cancer.yaml"
)


def test_status_reports_the_offline_backend_and_probes_only_to_operators() -> (
    None
):
    data = _client().get("/status").json()
    assert data["provider"] == "engine"
    assert data["llm_backend"] == "offline"
    assert data["probes"] is None
    operator = make_operator_client().get("/status").json()
    assert set(operator["probes"]) == {"mcp", "pubmed", "web_search"}


@pytest.mark.parametrize(
    ("mcp", "pubmed", "web_search", "review_available"),
    [
        (
            ProbeResult(available=True, state="up"),
            ProbeResult(available=False, state="down"),
            ProbeResult(available=False, state="down"),
            False,
        ),
        (
            ProbeResult(available=True, state="up"),
            ProbeResult(available=True, state="up"),
            ProbeResult(available=True, state="up"),
            True,
        ),
        (
            ProbeResult(
                available=False, state="error", error="probe timed out after 3s"
            ),
            ProbeResult(available=False, state="down"),
            ProbeResult(available=False, state="down"),
            False,
        ),
    ],
    ids=["needs-both", "all-up", "error-is-not-down"],
)
def test_status_derives_literature_and_connector_availability_from_probes(
    monkeypatch: pytest.MonkeyPatch,
    mcp: ProbeResult,
    pubmed: ProbeResult,
    web_search: ProbeResult,
    review_available: bool,
) -> None:
    _patch_probes(monkeypatch, mcp, pubmed, web_search)

    data = make_operator_client().get("/status").json()

    assert data["literature_review_available"] is review_available
    assert data["web_search_available"] is web_search.available
    assert (
        any(item["id"] == "web_search" for item in data["connectors"])
        is web_search.available
    )
    for name, probe in (("mcp", mcp), ("pubmed", pubmed)):
        assert data["probes"][name] == {
            "state": probe.state,
            "error": probe.error,
        }


@pytest.mark.parametrize("operator", [True, False])
def test_docs_and_the_docs_pointer_are_operator_only(operator: bool) -> None:
    # Private API docs 404 so anonymous probes cannot distinguish hidden routes
    # from absent ones.
    client = make_operator_client() if operator else _client()

    assert client.get("/").json()["docs"] == ("/docs" if operator else None)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == (200 if operator else 404), path


def _seed_interrupted_engine_run(isolated_db: str) -> str:
    interrupted = seed_run(
        "interrupted goal", profile="default", db_path=isolated_db
    )
    runs.update_run_status(
        interrupted.id, RunStatus.RUNNING, db_path=isolated_db
    )
    seed_checkpoint(
        interrupted.id,
        {"provider": "engine", "state": {"hypotheses": []}},
        stage="engine_task:test",
        db_path=isolated_db,
    )
    return interrupted.id


def test_lifespan_reconciles_interrupted_runs_and_seeds_demo_data(
    isolated_db: str,
) -> None:
    # TestClient only enters lifespan as a context manager; construction alone
    # does not exercise startup.
    import app.main as main_module

    interrupted = seed_run(
        "interrupted goal",
        profile="default",
        provider="mock",
        db_path=isolated_db,
    )
    runs.update_run_status(
        interrupted.id, RunStatus.RUNNING, db_path=isolated_db
    )

    with TestClient(main_module.app) as client:
        res = client.get("/health")
        assert res.status_code == 200

    reconciled = runs.get_run(interrupted.id, db_path=isolated_db)
    assert reconciled is not None
    assert reconciled.status == RunStatus.FAILED.value
    assert reconciled.error and "restart" in reconciled.error

    demo_runs = views.list_runs(client_id=DEMO_CLIENT_ID, db_path=isolated_db)
    assert len(demo_runs) == 3


def test_lifespan_fails_on_unreadable_tools_config(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bad tool configuration must fail startup rather than silently selecting
    # different tools.
    import app.main as main_module

    monkeypatch.setattr(settings, "tools_config", "/no/such/tools.yaml")

    with (
        pytest.raises(RuntimeError, match="tools_config"),
        TestClient(main_module.app),
    ):
        pass


def test_status_reports_effective_tools_config(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.main as main_module

    monkeypatch.setattr(settings, "tools_config", _INDRA_CONFIG)

    with TestClient(main_module.app, client=("127.0.0.1", 50000)) as client:
        res = client.get("/status")
        assert res.status_code == 200
        body = res.json()
        assert body["tools_config"] == _INDRA_CONFIG
        assert body["tools_config_valid"] is True
        assert "indra_statements" in body["enabled_tools"]


def test_status_redacts_operator_fields_from_non_operators(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # MCP hostnames and credential state are operator internals; public
    # availability remains usable.

    monkeypatch.setattr(settings, "tools_config", _INDRA_CONFIG)

    body = _client().get("/status").json()

    assert body["mcp_server_url"] is None
    assert body["has_provider_key"] is None
    assert body["byok_enabled"] is None
    assert body["engine_importable"] is None
    assert body["supervisor_model_name"] is None
    assert body["tools_config"] is None
    assert body["tools_config_valid"] is None
    assert body["enabled_tools"] is None
    assert body["probes"] is None
    assert isinstance(body["connectors"], list)
    assert body["provider"] == "engine"
    assert "llm_backend" in body
    assert "model_name" in body


def test_status_reports_whether_email_can_actually_be_sent(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without SMTP, opt-in only creates invisible retry-exhausted notification
    # tasks.
    import app.main as main_module

    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_from_email", "")
    with TestClient(main_module.app) as client:
        assert (
            client.get("/status").json()["email_notifications_available"]
            is False
        )

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(settings, "smtp_from_email", "noreply@example.org")
    with TestClient(main_module.app) as client:
        assert (
            client.get("/status").json()["email_notifications_available"]
            is True
        )


def test_startup_prunes_checkpoints_but_never_vacuums(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # VACUUM waits for exclusive access while log writes continue; pruning must
    # never block serving writers.
    import app.main as main_module

    pruned = threading.Event()

    def _prune(*args: object, **kwargs: object) -> int:
        pruned.set()
        return 0

    monkeypatch.setattr(checkpoints, "prune_superseded_checkpoints", _prune)

    with TestClient(main_module.app) as client:
        assert client.get("/health").status_code == 200

    assert pruned.is_set(), "startup should still reclaim checkpoint rows"


def test_startup_does_not_block_on_run_recovery(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Run recovery after binding traffic; provider work before lifespan yield
    # causes healthcheck restart spirals.
    import app.main as main_module
    import app.runs as runs_module

    resumed = threading.Event()

    async def slow_resume(run_ids: list[str]) -> None:
        resumed.set()
        await asyncio.sleep(30)

    async def _no_seed(db_path: str | None = None) -> None:
        # Stub demo compute so the timing assertion measures recovery scheduling
        # rather than seed work.
        return None

    monkeypatch.setattr(runs_module, "resume_interrupted_runs", slow_resume)
    monkeypatch.setattr(main_module, "seed_demo_runs", _no_seed)
    _seed_interrupted_engine_run(isolated_db)

    started = time.monotonic()
    with TestClient(main_module.app) as client:
        startup_seconds = time.monotonic() - started
        assert client.get("/health").status_code == 200
    assert resumed.is_set()
    assert startup_seconds < 10


# Queue/disk degradation returns HTTP 200 so liveness probes cannot kill
# productive runs.


def _health_running_run(db_path: str, goal: str = "queue health goal") -> str:
    run = seed_run(goal)
    runs.update_run_status(run.id, RunStatus.RUNNING, db_path=db_path)
    return run.id


def _health_enqueue(run_id: str, key: str, db_path: str, **kwargs: Any) -> str:
    task = enqueue_task(
        run_id, "engine.node.ranking", key, **kwargs, db_path=db_path
    )
    return task.id


def _expire_lease(task_id: str, db_path: str) -> None:
    # Expire the lease without changing attempts to model a worker that died
    # without failing its task.
    with db.connect(db_path) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
            (task_id,),
        )
        conn.commit()


def _snapshot_with_lease(
    db_path: str, *, max_attempts: int = 3, expired: bool = False
) -> tuple[str, QueueHealthSnapshot]:
    run_id = _health_running_run(db_path)
    task_id = _health_enqueue(
        run_id, "leased", db_path, max_attempts=max_attempts
    )
    leased = store.claim_task("w1", run_id=run_id, db_path=db_path)
    assert leased is not None and leased.id == task_id
    if expired:
        _expire_lease(task_id, db_path)
    return run_id, queue_health_snapshot(db_path=db_path)


def test_snapshot_without_active_work_has_nothing_stalled(
    isolated_db: str,
) -> None:
    assert queue_health_snapshot(db_path=isolated_db) == QueueHealthSnapshot(
        (), 0, 0, 0
    )
    done = seed_run("done goal")
    runs.update_run_status(done.id, RunStatus.COMPLETED, db_path=isolated_db)
    run_id = _health_running_run(isolated_db)
    _health_enqueue(run_id, "queued", isolated_db)

    snapshot = queue_health_snapshot(db_path=isolated_db)

    assert snapshot.stalled_run_ids == ()
    assert snapshot.queued_depth == 1


def test_active_and_rescuable_leases_are_not_stalled(isolated_db: str) -> None:
    _, active = _snapshot_with_lease(isolated_db)
    assert active.stalled_run_ids == ()

    _, rescuable = _snapshot_with_lease(isolated_db, expired=True)
    assert rescuable.stalled_run_ids == ()
    assert rescuable.rescuable_leases == 1


def test_orphaned_exhausted_lease_leaves_run_stalled(isolated_db: str) -> None:
    # A dead exhausted lease has no owner to fail it; health must expose the
    # stranded running state.
    run_id, snapshot = _snapshot_with_lease(
        isolated_db, max_attempts=1, expired=True
    )

    assert snapshot.stalled_run_ids == (run_id,)
    assert snapshot.rescuable_leases == 0
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "running"


def test_failed_task_counted_without_stalling_active_sibling(
    isolated_db: str,
) -> None:
    run_id = _health_running_run(isolated_db)
    doomed = _health_enqueue(run_id, "doomed", isolated_db, max_attempts=1)
    _health_enqueue(run_id, "survivor", isolated_db, max_attempts=1)
    leased = store.claim_task("w1", run_id=run_id, db_path=isolated_db)
    assert leased is not None and leased.id == doomed
    store.fail_task(
        leased.id, "w1", "boom", retryable=False, db_path=isolated_db
    )

    snapshot = queue_health_snapshot(db_path=isolated_db)

    assert snapshot.failed_tasks == 1
    assert snapshot.stalled_run_ids == ()


def test_check_queue_flags_a_stalled_run_and_reports_errors(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert diagnostics.check_queue(isolated_db) == HealthCheck(ok=True)
    run_id, _ = _snapshot_with_lease(isolated_db, max_attempts=1, expired=True)

    stalled = diagnostics.check_queue(isolated_db)

    assert stalled.ok is False
    assert stalled.detail is not None and run_id in stalled.detail

    def _boom(db_path: str | None = None) -> QueueHealthSnapshot:
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(diagnostics, "queue_health_snapshot", _boom)
    failed = diagnostics.check_queue()
    assert failed.ok is False
    assert failed.detail is not None and "db unreachable" in failed.detail


def test_check_disk_flags_only_space_below_the_floor(tmp_path: Any) -> None:
    path = str(tmp_path / "db.sqlite")

    assert diagnostics.check_disk(path, min_free_bytes=0).ok is True
    low = diagnostics.check_disk(path, min_free_bytes=10**18)
    assert low.ok is False
    assert low.detail is not None and "floor" in low.detail


@pytest.mark.parametrize(
    ("store_ok", "queue_ok", "disk_ok", "status"),
    [
        (True, False, False, diagnostics.DEGRADED),
        (False, True, True, diagnostics.UNHEALTHY),
    ],
)
def test_queue_and_disk_degrade_health_but_a_down_store_is_unhealthy(
    store_ok: bool, queue_ok: bool, disk_ok: bool, status: str
) -> None:
    assert (
        diagnostics.derive_overall_health(
            HealthCheck(ok=store_ok),
            HealthCheck(ok=True),
            HealthCheck(ok=queue_ok),
            HealthCheck(ok=disk_ok),
        )
        == status
    )


@pytest.mark.parametrize(("ttl", "calls"), [(60.0, 1), (0.0, 2)])
def test_queue_and_disk_health_cache_honours_its_ttl(
    monkeypatch: pytest.MonkeyPatch, ttl: float, calls: int
) -> None:
    seen: list[int] = []

    def _stub_queue(db_path: str | None = None) -> HealthCheck:
        seen.append(1)
        return HealthCheck(ok=True)

    monkeypatch.setattr(diagnostics, "check_queue", _stub_queue)
    monkeypatch.setattr(
        diagnostics, "check_disk", lambda db_path=None: HealthCheck(ok=True)
    )
    monkeypatch.setattr(settings, "health_check_cache_ttl_seconds", ttl)
    diagnostics.clear_health_check_cache()

    diagnostics.queue_and_disk_health_cached()
    diagnostics.queue_and_disk_health_cached()

    assert len(seen) == calls


def test_health_is_healthy_while_a_run_progresses(isolated_db: str) -> None:
    run_id = _health_running_run(isolated_db)
    _health_enqueue(run_id, "queued", isolated_db)

    res = _client().get("/health")

    assert res.status_code == 200
    assert res.json()["status"] == "healthy"
    assert set(res.json()["checks"]) == {"store", "engine", "queue", "disk"}


def test_health_degrades_at_200_when_a_run_is_stalled(
    isolated_db: str,
) -> None:
    run_id, _ = _snapshot_with_lease(isolated_db, max_attempts=1, expired=True)

    res = _client().get("/health")

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "degraded"
    assert data["checks"]["queue"]["ok"] is False
    operator = _operator_client().get("/health").json()
    assert run_id in (operator["checks"]["queue"]["detail"] or "")
    assert data["checks"]["queue"]["detail"] is None


def test_health_degrades_at_200_when_disk_is_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "health_check_min_free_disk_bytes", 10**18)

    res = _client().get("/health")

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "degraded"
    assert data["checks"]["disk"]["ok"] is False
