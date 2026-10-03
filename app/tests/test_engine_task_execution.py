"""Tests for engine execution 2."""

from __future__ import annotations

import dataclasses
import time
from typing import Any

import pytest
from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.llm import (
    ModelCallStats,
    current_run_call_count,
    record_call,
    release_run_call_budget,
)
from co_scientist.llm.admission.call_budget import record_provider_request
from co_scientist.models import (
    Article,
    ExecutionMetrics,
    Hypothesis,
    HypothesisReview,
)
from co_scientist.workflow_topology import LiteratureGated
from litellm.exceptions import APIError

import app.engine_adapter.drain.final_state as drain_claim_grounding
import app.engine_tasks.fanout as engine_tasks_fanout_items
import app.engine_tasks.support as engine_tasks_context
from app import engine_tasks, safety, store, task_worker
from app.engine_tasks import fanout_aggregates as engine_tasks_fanout_aggregates
from app.engine_tasks import finalize as engine_tasks_node
from app.engine_tasks import node as engine_tasks_restore
from app.engine_tasks import ranking as engine_tasks_ranking
from app.engine_tasks import runtime as engine_tasks_runtime
from app.engine_tasks import support as engine_tasks_support
from app.engine_tasks.runtime import ProductionEngineTaskRuntime
from app.engine_tasks.support import TaskCommit
from app.run_modes import RUN_TIER_DEFAULTS, resolved_run_config
from app.safety import ScreenSubject
from tests._engine_tasks_helpers import (
    FakeEngineTaskRuntime,
    _Generator,
    _install_plain_fake_judge,
    _install_runtime,
    _milestones,
    _patch_generator,
    _patch_restore_generator,
    _patch_task_node,
    _RankingSeed,
    _run_ranking_node,
    _seed_checkpoint,
    _seed_ranking_node,
    _task_state,
)

# Dispatch and lifecycle tests for the durable engine executor.
#
# Supervisor priority reaching a successor, the specialist task chain,
# finalize's post-drain stage events, and generic node-completion milestones.


def _priority_state(run_id: str, deferred_id: str) -> dict[str, Any]:
    """State carrying a next-task priority and a reprioritize queue action."""
    return {
        **_task_state(run_id),
        "next_task_priority": 97,
        "supervisor_queue_actions": [
            {
                "action": "reprioritize",
                "task_id": deferred_id,
                "priority": 98,
                "reason": "Review backlog is urgent.",
            }
        ],
    }


def _seed_orchestrator_task(run_id: str, db_path: str) -> tuple[Any, Any]:
    """Seed a claimed orchestrator task plus a low-priority deferred task."""
    store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage="seed",
            schema_version=1,
            last_event_seq=0,
            state={"provider": "engine"},
        ),
        db_path=db_path,
    )
    queued = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.orchestrator",
            inputs={"checkpoint_seq": 1},
            idempotency_key="orchestrator-priority",
        ),
        db_path=db_path,
    )
    task = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert task is not None and task.id == queued.id
    deferred = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.reflect",
            inputs={},
            idempotency_key="deferred-reflection",
            priority=10,
        ),
        db_path=db_path,
    )
    return task, deferred


def test_orchestrator_priority_reaches_durable_successor(
    isolated_db: str,
) -> None:
    """The Supervisor's selected priority controls queue claim order."""
    run = store.create_run("Priority science", "standard", "engine", {})
    task, deferred = _seed_orchestrator_task(run.id, isolated_db)

    engine_tasks_support._save_state_and_enqueue(
        engine_tasks_context.TaskCommit(task, 1, isolated_db),
        _priority_state(run.id, deferred.id),
        "generate",
    )

    successor = store.list_tasks(run.id, db_path=isolated_db)[-1]
    assert successor.task_type == "engine.node.generate"
    assert successor.priority == 97
    updated = store.get_task(deferred.id, db_path=isolated_db)
    assert updated is not None and updated.priority == 98


def test_node_commit_persists_live_metrics(isolated_db: str) -> None:
    """A node commit writes readable metrics before the run finalizes.

    ``GET /api/runs/{id}/metrics`` (``store.get_run_metrics``) has exactly
    one writer before this fix: the finalize drain. A run in the middle
    of its work -- one node committed, nowhere near finalizing -- must
    already show that node's real llm_calls, not null (finding L14).
    """
    run = store.create_run("Live metrics science", "standard", "engine", {})
    task, deferred = _seed_orchestrator_task(run.id, isolated_db)
    state = {
        **_priority_state(run.id, deferred.id),
        "metrics": ExecutionMetrics(llm_calls=7, hypothesis_count=3),
    }

    assert store.get_run_metrics(run.id, db_path=isolated_db) is None

    engine_tasks_support._save_state_and_enqueue(
        engine_tasks_context.TaskCommit(task, 1, isolated_db),
        state,
        "generate",
    )

    live = store.get_run_metrics(run.id, db_path=isolated_db)
    assert live is not None
    assert live["llm_calls"] == 7
    assert live["hypothesis_count"] == 3


def test_node_commit_persists_supervisor_performance_assessment(
    isolated_db: str,
) -> None:
    """The Supervisor's performance_assessment reaches the metrics row.

    Written at ``supervisor.py:254`` into ``supervisor_guidance`` and read
    by nothing in production (finding F5). Persisting it onto the same
    row the live-metrics fix (L14) already writes makes it inspectable
    over the existing ``GET /api/runs/{id}/metrics`` endpoint without a
    second persisted artifact -- and without building the weighted
    allocator that would consume it (Stage 11, out of scope here).
    """
    run = store.create_run("Assessed science", "standard", "engine", {})
    task, deferred = _seed_orchestrator_task(run.id, isolated_db)
    assessment = {
        "generation": {"yield": "high", "notes": "productive so far"},
        "evolution": {"yield": "low", "notes": "little improvement"},
    }
    state = {
        **_priority_state(run.id, deferred.id),
        "supervisor_guidance": {"performance_assessment": assessment},
    }

    engine_tasks_support._save_state_and_enqueue(
        engine_tasks_context.TaskCommit(task, 1, isolated_db),
        state,
        "generate",
    )

    live = store.get_run_metrics(run.id, db_path=isolated_db)
    assert live is not None
    assert live["performance_assessment"] == assessment


@pytest.mark.asyncio
async def test_worker_consumes_independent_specialist_task_chain(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One run advances through separately committed and leased node tasks."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    engine_tasks.enqueue_bootstrap(run.id, db_path=isolated_db)
    generator = _Generator(_task_state(run.id))
    _patch_generator(monkeypatch, generator, restore=True, screen=True)

    successors = {"supervisor": "research_overview", "research_overview": None}
    finalized: list[str] = []

    async def execute(
        name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        return state, successors[name]

    async def finalize(task: Any, **_: Any) -> dict[str, Any]:
        finalized.append(task.run_id)
        store.update_run_status(task.run_id, store.RunStatus.COMPLETED)
        return {"run_id": task.run_id, "status": "completed"}

    _patch_task_node(monkeypatch, execute)
    monkeypatch.setitem(
        engine_tasks._ENGINE_TASK_DISPATCH,
        engine_tasks_support.FINALIZE_TASK,
        finalize,
    )
    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)
    assert finalized == [run.id]

    tasks = store.list_tasks(run.id, db_path=isolated_db)
    # Bootstrap's real commit plans its own portfolio (finding F4) from the
    # real route table before this fixture's `execute` ever runs: with
    # `mcp_available=False`, supervisor's real successor is `generate`, so
    # bootstrap enqueues it as a lookahead row chained behind supervisor.
    # The fixture then hands supervisor a fictional successor
    # (`research_overview`) to exercise independent task leasing without
    # the full real graph, which supersedes that lookahead guess -- cancelled
    # in the same transaction as the real "research_overview" successor
    # (`app.engine_tasks.portfolio._cancel_stale_planned_row`), not removed
    # from the row history `list_tasks` returns.
    assert [task.task_type for task in tasks] == [
        "engine.bootstrap",
        "engine.node.supervisor",
        "engine.node.generate",
        "engine.node.research_overview",
        "engine.finalize",
    ]
    by_type = {task.task_type: task.status for task in tasks}
    assert by_type.pop("engine.node.generate") == "cancelled"
    assert all(status == "completed" for status in by_type.values())
    # Milestones append once in commit order, from the canonical
    # `supervisor.plan` and `research_overview` builders (see events.py).
    assert _milestones(run.id, db_path=isolated_db) == [
        "Research plan ready — supervisor complete",
        "Research overview ready",
    ]


def _dispatch_seed_finalize_task(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> Any:
    """Seed a grounded finalize task; patch restore to the fixture generator."""
    hypothesis = Hypothesis(
        text="Astrocyte lactate accelerates synaptic ATP recovery.",
        literature_grounding=(
            "Astrocyte lactate accelerates synaptic ATP recovery."
        ),
    )
    state = _task_state(run_id)
    state["hypotheses"] = [hypothesis]
    # An article whose abstract carries the hypothesis's claim so grounding
    # finds support (blocked=0) rather than quarantining it as unsupported.
    state["articles"] = [
        Article(
            title="Synaptic energetics",
            url="https://example.org/synaptic",
            abstract="Astrocyte lactate accelerates synaptic ATP recovery.",
        )
    ]
    _seed_checkpoint(run_id, state, db_path=db_path)
    queued = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=engine_tasks_support.FINALIZE_TASK,
            inputs={},
            idempotency_key="finalize",
        ),
        db_path=db_path,
    )
    task = store.claim_task(
        "finalize-dispatch-worker", run_id=run_id, db_path=db_path
    )
    assert task is not None and task.id == queued.id
    # Restore builds a real generator otherwise; the fixture generator carries a
    # null tool_registry, which restore_workflow_state accepts.
    _patch_restore_generator(monkeypatch, _Generator(state))
    return task


def _assert_post_drain_counts(by_type: dict[str, Any]) -> None:
    """Pin the safety/grounding/citation-audit stage-event payloads."""
    assert set(by_type["safety.hypothesis"]) == {
        "screened",
        "blocked",
        "eligible",
        "activity",
    }
    assert by_type["safety.hypothesis"] == {
        "screened": 1,
        "blocked": 0,
        "eligible": 1,
        "activity": "safety",
    }
    # "assessed" and "grounded" are distinct: a blocked hypothesis was still
    # assessed, so reporting the assessed total as "grounded" double-counts
    # every block.
    assert set(by_type["citation.grounding"]) == {
        "assessed",
        "grounded",
        "blocked",
        "eligible",
        "activity",
    }
    assert by_type["citation.grounding"] == {
        "assessed": 1,
        "grounded": 1,
        "blocked": 0,
        "eligible": 1,
        "activity": "other",
    }
    # No citation_map on the hypothesis, so every state count is zero, but the
    # full citation-state vocabulary is present in the audit payload; the
    # discriminator is the one non-count key.
    citation_audit = dict(by_type["citation_audit"])
    assert citation_audit.pop("activity") == "other"
    assert citation_audit
    assert all(isinstance(v, int) for v in citation_audit.values())


@pytest.mark.asyncio
async def test_execute_finalize_emits_post_drain_stage_events(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The durable finalize task emits the three post-drain stage events.

    Pins the production ``execute_finalize`` path end to end: it must pop the
    drain's ``safety_counts``/``grounding_counts`` (which are not
    ``finalize_report`` kwargs), emit ``safety.hypothesis``,
    ``citation.grounding``, and ``citation_audit`` from them, and still run
    ``finalize_report`` to completion. Without the pop this path would raise
    ``TypeError: finalize_report() got an unexpected keyword argument``.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    task = _dispatch_seed_finalize_task(run.id, monkeypatch, isolated_db)

    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    # finalize_report ran to completion (no leaked kwargs, no TypeError).
    assert result["status"] == store.RunStatus.COMPLETED.value
    assert store.get_latest_report(run.id, db_path=isolated_db) is not None

    events = store.list_events(run.id, db_path=isolated_db)
    by_type = {e["type"]: e["payload"] for e in events}
    _assert_post_drain_counts(by_type)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("node_name", "extra_state", "expected_milestone"),
    [
        pytest.param(
            "reflection",
            {
                "hypotheses": [
                    Hypothesis(
                        text="Reviewed idea",
                        reviews=[
                            HypothesisReview(
                                review_summary="ok",
                                scores={},
                                safety_ethical_concerns="",
                                detailed_feedback={},
                                constructive_feedback="",
                                overall_score=70.0,
                            )
                        ],
                    )
                ]
            },
            "1 hypotheses reviewed",
            id="reflection",
        ),
        pytest.param(
            "evolve",
            {
                "hypotheses": [
                    Hypothesis(
                        text="Evolved idea", evolution_history=["refined"]
                    )
                ]
            },
            "1 hypotheses evolved (iteration 0)",
            id="evolve",
        ),
        pytest.param(
            "proximity",
            {
                "proximity_graph": {
                    "edges": [
                        {"source": "h1", "target": "h2", "cluster_id": "c1"}
                    ]
                }
            },
            "1 clusters identified",
            id="proximity",
        ),
        pytest.param(
            "meta_review",
            {"meta_review": {"summary": "Synthesis complete."}},
            "Meta-review complete",
            id="meta_review",
        ),
    ],
)
async def test_generic_node_completion_emits_matching_milestone(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    node_name: str,
    extra_state: dict[str, Any],
    expected_milestone: str,
) -> None:
    """The remaining milestone-bearing nodes append their canonical chat text.

    Covers the four node types (reflection, evolve, proximity, meta_review)
    carrying a milestone builder (see events.py's ``_MILESTONE_BUILDERS``)
    that no other durable-executor test happens to exercise through
    ``execute_node_task``'s generic completion path. The rest are covered
    elsewhere: supervisor.plan and research_overview by
    ``test_worker_consumes_independent_specialist_task_chain``, generate by
    ``test_generation_strategies_are_independently_leased_and_aggregated``,
    ranking by ``test_ranking_matches_..._checkpointed_tasks``, and
    deep_verification by ``test_verification_children_..._aggregator``.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    checkpoint_seq = _seed_checkpoint(run.id, _task_state(run.id))
    node = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}{node_name}",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"milestone-{node_name}",
        ),
        db_path=isolated_db,
    )
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == node.id

    async def execute(
        _name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        return {**state, **extra_state}, None

    _patch_task_node(monkeypatch, execute)
    result = await engine_tasks.execute_node_task(leased, db_path=isolated_db)
    assert store.complete_task(leased.id, "worker", result, db_path=isolated_db)
    assert _milestones(run.id, db_path=isolated_db) == [expected_milestone]


# Regression guard for the b82f9162 finalize-lease incident (2026-09-06).
#
# Finalize's claim-grounding wave used to run synchronously on the durable
# task's own event loop, which starved ``task_worker._heartbeat_lease`` for
# the wave's whole duration -- a healthy finalize task lost its lease and its
# retry budget under a real production ultra run.
# ``drain.claim_grounding._assess_claims`` now runs that wave off the loop
# (``async_bridge.run_off_loop``) so the heartbeat keeps renewing while it
# runs; see the root AGENTS.md lease/heartbeat Gotcha.


def _lease_seed_finalize_task(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> Any:
    """Seed a groundable finalize task, mirroring the dispatch fixture."""
    hypothesis = Hypothesis(
        text="Astrocyte lactate accelerates synaptic ATP recovery.",
        literature_grounding=(
            "Astrocyte lactate accelerates synaptic ATP recovery."
        ),
    )
    state = _task_state(run_id)
    state["hypotheses"] = [hypothesis]
    state["articles"] = [
        Article(
            title="Synaptic energetics",
            url="https://example.org/synaptic",
            abstract="Astrocyte lactate accelerates synaptic ATP recovery.",
        )
    ]
    _seed_checkpoint(run_id, state, db_path=db_path)
    task = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=engine_tasks_support.FINALIZE_TASK,
            inputs={},
            idempotency_key="finalize",
        ),
        db_path=db_path,
    )
    _patch_restore_generator(monkeypatch, _Generator(state))
    return task


def _count_lease_renewals(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Patch ``store.renew_task_lease`` with a counter, return the counter.

    Mirrors ``test_task_worker_leases._count_lease_renewals``.
    """
    box = {"renewals": 0}
    real_renew = store.renew_task_lease

    def _renew(*args: Any, **kwargs: Any) -> bool:
        box["renewals"] += 1
        return real_renew(*args, **kwargs)

    monkeypatch.setattr(store, "renew_task_lease", _renew)
    return box


@pytest.mark.asyncio
async def test_finalize_lease_survives_a_slow_grounding_wave(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A grounding wave that outlives the lease interval still renews it.

    ``assess_hypothesis_claims`` is patched to a real (fast) call wrapped in
    a deliberate blocking ``time.sleep`` -- reproducing the incident's
    shape, a synchronous provider wave -- with the lease interval shrunk
    far below that sleep (``renew_every = lease_seconds / 3`` is well under
    it). The discriminator is the heartbeat's renewal count, not merely
    "the task eventually completes": awaiting a coroutine that resolves
    with no real suspension point (as a broken, on-loop wave would) never
    hands control back to the event loop at all, so the whole task runs to
    completion in one synchronous stretch and a competing worker never even
    gets to *try* claiming it -- that would pass a weaker assertion for the
    wrong reason. A live heartbeat renewing during the wave is the fix's
    actual, positive signature.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    task = _lease_seed_finalize_task(run.id, monkeypatch, isolated_db)
    renewals = _count_lease_renewals(monkeypatch)

    real_assess = (
        drain_claim_grounding.assess_hypothesis_claims  # type: ignore[attr-defined]
    )
    sleep_seconds = 0.3

    def _slow_assess(*args: Any, **kwargs: Any) -> Any:
        time.sleep(sleep_seconds)
        return real_assess(*args, **kwargs)

    monkeypatch.setattr(
        drain_claim_grounding, "assess_hypothesis_claims", _slow_assess
    )

    completed = await task_worker.run_once(
        "worker-a", db_path=isolated_db, lease_seconds=0.06
    )

    assert completed
    # A blocked loop still fires exactly one belated "catch up" renewal the
    # instant it finally regains control after the wave -- so ">= 1" alone
    # would not catch a regression. A live heartbeat renews on its own
    # schedule *throughout* the 0.3s wave (renew_every ~= 0.02s here), which
    # is several renewals, not one; measured fixed=6 vs. broken=1.
    assert renewals["renewals"] >= 3, (
        "the lease heartbeat barely renewed during the grounding wave -- "
        "the wave is blocking the task's event loop again"
    )
    persisted_run = store.get_run(run.id, db_path=isolated_db)
    assert persisted_run is not None
    assert persisted_run.status == "completed"
    saved = store.get_task(task.id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "completed"


# ``execute_engine_task`` scopes the run's LLM-call ceiling around dispatch.
#
# Mirrors ``test_byok_flow.py::test_execute_engine_task_scopes_the_credential``:
# that test pins the credential scope entered around dispatch, this one pins
# the LLM-call-budget scope entered beside it -- every completion the
# dispatched task makes is attributed to the run whose ``max_llm_calls`` came
# from its own resolved tier config, and the scope is gone once the task
# returns.


def _node_task(run_id: str) -> store.ScientificTask:
    """Shape a minimal node-task row for the dispatch/scope test."""
    return store.ScientificTask(
        id="task-1",
        run_id=run_id,
        task_type="engine.node.generate",
        status="leased",
        priority=90,
        inputs={},
        dependencies=(),
        provenance={},
        idempotency_key="engine.node.generate:0",
        budget={},
        attempt=1,
        max_attempts=3,
        lease_owner="test",
        lease_expires_at=None,
        result=None,
        error=None,
        created_at=0.0,
        updated_at=0.0,
        started_at=None,
        completed_at=None,
    )


async def test_execute_engine_task_scopes_the_llm_call_ceiling(
    monkeypatch: Any,
) -> None:
    run = store.create_run(
        "Budget scoping",
        "express",
        "engine",
        resolved_run_config({"tier": "express"}),
    )
    try:
        seen: dict[str, int] = {}

        async def fake_node_task(
            task: Any, *, db_path: str | None = None
        ) -> dict[str, Any]:
            record_provider_request()
            record_provider_request()
            seen["count_during"] = current_run_call_count(run.id)
            return {"status": "completed"}

        monkeypatch.setattr(engine_tasks, "execute_node_task", fake_node_task)
        await engine_tasks.execute_engine_task(_node_task(run.id))

        assert seen["count_during"] == 2
        # A second task on the same run must see the running count carried
        # forward, not reset -- a durable run is many short-lived tasks.
        seen2: dict[str, int] = {}

        async def fake_node_task_2(
            task: Any, *, db_path: str | None = None
        ) -> dict[str, Any]:
            record_provider_request()
            seen2["count_during"] = current_run_call_count(run.id)
            return {"status": "completed"}

        monkeypatch.setattr(engine_tasks, "execute_node_task", fake_node_task_2)
        await engine_tasks.execute_engine_task(_node_task(run.id))
        assert seen2["count_during"] == 3

        # The scope is gone once the task returns: an ambient call outside
        # any task must not attribute to the last-dispatched run.
        record_provider_request()
        assert current_run_call_count(run.id) == 3
    finally:
        release_run_call_budget(run.id)


async def test_execute_engine_task_enforces_the_ceiling(
    monkeypatch: Any,
) -> None:
    """A run already over its ceiling refuses the next request outright."""
    tier_ceiling = RUN_TIER_DEFAULTS["express"]["max_llm_calls"]
    run = store.create_run(
        "Budget enforcement",
        "express",
        "engine",
        resolved_run_config({"tier": "express"}),
    )
    try:
        from co_scientist.exceptions import LLMCallBudgetExceededError

        async def spend_to_ceiling(
            task: Any, *, db_path: str | None = None
        ) -> dict[str, Any]:
            for _ in range(tier_ceiling):
                record_provider_request()
            return {"status": "completed"}

        monkeypatch.setattr(engine_tasks, "execute_node_task", spend_to_ceiling)
        await engine_tasks.execute_engine_task(_node_task(run.id))
        assert current_run_call_count(run.id) == tier_ceiling

        async def one_more(
            task: Any, *, db_path: str | None = None
        ) -> dict[str, Any]:
            record_provider_request()
            return {"status": "completed"}

        monkeypatch.setattr(engine_tasks, "execute_node_task", one_more)
        try:
            await engine_tasks.execute_engine_task(_node_task(run.id))
            raised = False
        except LLMCallBudgetExceededError:
            raised = True
        assert raised, "the request past the ceiling must be refused"
    finally:
        release_run_call_budget(run.id)


# A run whose terminal overview degraded still publishes its report.
#
# Production run 49a509b0 committed 146 tasks and published nothing: the
# terminal ``engine.node.research_overview`` task spent its three durable
# attempts on an unreachable provider, ``store.fail_task`` settled the run
# ``failed``, and ``engine.finalize`` -- enqueued only ever as that node's
# ``None`` successor -- was never created, so ``GET /report.md`` 404'd on a
# run with a full tournament behind it.
#
# The engine half (the node degrading instead of raising) is pinned in
# ``engine/tests/test_node_provider_degradation.py``. This is the
# consequence on the durable path the production run actually took: the
# successor is still enqueued, the report is still written, the run does
# not settle ``failed``, and the report payload names the section that went
# missing -- through the existing ``degraded_sections`` seam, not a new
# field.


_UPSTREAM = APIError(
    status_code=500,
    message="OpenrouterException - Upstream error from Nvidia: overloaded",
    llm_provider="openrouter",
    model="minimax/minimax-m3:free",
)


def _grounded_state(run_id: str) -> dict[str, Any]:
    """One publishable hypothesis whose claim an article's abstract carries."""
    claim = "Astrocyte lactate accelerates synaptic ATP recovery."
    hypothesis = Hypothesis(text=claim, literature_grounding=claim)
    hypothesis.review_disposition = "viable"
    state = _task_state(run_id)
    state["hypotheses"] = [hypothesis]
    state["articles"] = [
        Article(
            title="Synaptic energetics",
            url="https://example.org/synaptic",
            abstract=claim,
        )
    ]
    return state


def _seed_overview_task(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> None:
    """Seed the terminal overview task with an unreachable provider."""
    state = _grounded_state(run_id)
    checkpoint_seq = _seed_checkpoint(run_id, state, db_path=db_path)
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.research_overview",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="overview",
        ),
        db_path=db_path,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True, screen=True)

    async def _unreachable(*_: Any, **__: Any) -> dict[str, Any]:
        raise _UPSTREAM

    monkeypatch.setattr(ro, "call_llm_json", _unreachable)


@pytest.mark.asyncio
async def test_degraded_overview_still_reaches_a_written_report(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The overview task completes, finalize runs, and a report exists."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    _seed_overview_task(run.id, monkeypatch, isolated_db)

    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)

    by_type = {
        task.task_type: task.status
        for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    assert by_type["engine.node.research_overview"] == "completed"
    assert by_type[engine_tasks_support.FINALIZE_TASK] == "completed"

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["markdown_text"]

    run_row = store.get_run(run.id, db_path=isolated_db)
    assert run_row is not None
    assert run_row.status != store.RunStatus.FAILED.value


@pytest.mark.asyncio
async def test_the_report_names_the_overview_as_a_degraded_section(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The degradation is visible in the run record, not just the log."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    _seed_overview_task(run.id, monkeypatch, isolated_db)

    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert "research_overview" in report["payload"]["degraded_sections"]


@pytest.mark.asyncio
async def test_the_overview_degrades_only_once_its_retries_are_spent(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every durable attempt is spent before the blank section is accepted.

    The earlier extended run bc77950f met the same provider trouble and
    synthesized a full overview on its third durable attempt. Degrading on
    the first would trade that recovery for a permanently blank section,
    so the task must arrive at its fallback with its budget exhausted.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    _seed_overview_task(run.id, monkeypatch, isolated_db)

    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)

    overview = next(
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.task_type == "engine.node.research_overview"
    )
    assert overview.status == "completed"
    assert overview.attempt == overview.max_attempts == 3
    assert len(overview.attempts) == 2


def _restored_state(attempt: int, run_id: str, db_path: str) -> dict[str, Any]:
    """Restore a node task's state the way the worker does on ``attempt``."""
    from co_scientist.checkpoint import serialize_workflow_state

    state = _task_state(run_id)
    task = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.research_overview",
            inputs={},
            idempotency_key=f"overlay-{attempt}",
        ),
        db_path=db_path,
    )
    checkpoint = {
        "state": {
            "provider": "engine",
            **serialize_workflow_state(state, last_event_seq=0),
        }
    }
    return engine_tasks_restore._restore_node_task_state(
        dataclasses.replace(task, attempt=attempt),
        checkpoint,
        _Generator(state),
        {},
        db_path,
    )


def test_the_restored_state_names_the_task_s_last_attempt(
    isolated_db: str,
) -> None:
    """The flag the node reads is the worker's own retry-left formula.

    Mirrors ``task_worker.outcomes._is_terminal_failure``: an attempt at
    the ceiling is the one whose failure settles the task, so it is the
    one that must degrade rather than raise.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})

    first = _restored_state(1, run.id, isolated_db)
    last = _restored_state(3, run.id, isolated_db)

    assert first["durable_retries_remain"] is True
    assert last["durable_retries_remain"] is False


# Durable-path successors are read from the engine's route table.
#
# The durable task path is the only path production runs, and every node
# commit on it used to name its successor as a literal --
# ``"comprehensive_reflection"``, ``"ranking"``, ``"orchestrator"``, and a
# verbatim re-implementation of the graph's MCP branch after ``generate``.
# ``co_scientist.workflow_topology.WORKFLOW_ROUTES`` is the table both the
# in-process graph and ``co_scientist.task_runtime.next_task_type`` read, and
# ``engine/tests/test_task_runtime.py`` pins the two against each other -- so
# a re-route would have applied to the engine's own routing and silently not
# to production, while a green suite reported routing as verified.
#
# These tests divert the route table and require the durable commits to
# follow the diversion, so spelling a successor out on the app side again
# fails rather than passing until it reaches a run.


# The nodes whose successor the durable path schedules itself, instead of
# taking the one ``execute_task_node`` hands back from the engine. Every
# one of them commits outside the graph: the four fan-out aggregates and
# the tournament finalizer.
_ROUTED_NODES = (
    "generate",
    "review",
    "comprehensive_reflection",
    "deep_verification",
    "ranking",
)

# A real graph node that is not the true successor of any node above, so
# scheduling it can only mean the diverted table was consulted.
_DIVERTED_TO = "proximity"


async def _schedule_successor(
    node: str, commit: TaskCommit, state: dict[str, Any]
) -> str:
    """Run the real durable commit helper that schedules ``node``'s successor.

    Args:
        node: Engine node being committed.
        commit: The leased task, its checkpoint sequence, and db path.
        state: Workflow state the commit checkpoints.

    Returns:
        The id of the successor task the commit enqueued.
    """
    if node == "ranking":
        result = await engine_tasks_ranking._commit_ranking_finalize(
            commit, state, {}
        )
        return str(result["successor_task_id"])
    advance = engine_tasks_fanout_aggregates._checkpoint_and_advance
    _, successor_id = await advance(commit, state, node)
    return str(successor_id)


async def _commit_node(
    run_id: str, node: str, db_path: str, *, mcp_available: bool = False
) -> str:
    """Commit one durable node and return the task type it scheduled.

    Args:
        run_id: Run the node task belongs to.
        node: Engine node to commit.
        db_path: Per-test SQLite database.
        mcp_available: MCP availability the committed state carries, which
            is what the graph's post-``generate`` branch routes on.

    Returns:
        The durable task type of the enqueued successor.
    """
    state = _task_state(run_id)
    state["mcp_available"] = mcp_available
    checkpoint_seq = _seed_checkpoint(run_id, state, db_path=db_path)
    queued = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}{node}",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{node}:commit",
        ),
        db_path=db_path,
    )
    task = store.claim_task(f"routing-{node}", run_id=run_id, db_path=db_path)
    assert task is not None and task.id == queued.id
    successor_id = await _schedule_successor(
        node, TaskCommit(task, checkpoint_seq, db_path), state
    )
    successor = store.get_task(successor_id, db_path=db_path)
    assert successor is not None
    return successor.task_type


@pytest.mark.asyncio
@pytest.mark.parametrize("node", _ROUTED_NODES)
async def test_durable_successor_matches_the_engine_route_table(
    isolated_db: str, node: str
) -> None:
    """Each durable commit schedules exactly what the route table names.

    The expectation is read from the table rather than written out, so it
    tracks a re-route instead of pinning today's topology in place.
    """
    from co_scientist.task_runtime import next_task_type

    run = store.create_run("Durable routing", "standard", "engine", {})
    scheduled = await _commit_node(run.id, node, isolated_db)
    expected = next_task_type(node, {"mcp_available": False})
    assert scheduled == f"{engine_tasks.NODE_TASK_PREFIX}{expected}"


@pytest.mark.asyncio
@pytest.mark.parametrize("node", _ROUTED_NODES)
async def test_durable_successor_follows_a_rerouted_graph(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, node: str
) -> None:
    """A graph re-route reaches production, not just the engine's routing."""
    from co_scientist import workflow_topology

    monkeypatch.setitem(workflow_topology.WORKFLOW_ROUTES, node, _DIVERTED_TO)
    run = store.create_run("Durable routing", "standard", "engine", {})
    scheduled = await _commit_node(run.id, node, isolated_db)
    assert scheduled == f"{engine_tasks.NODE_TASK_PREFIX}{_DIVERTED_TO}"


# ``generate``'s MCP branch, re-routed to the opposite successor.
_INVERTED_GENERATE_ROUTE = LiteratureGated(on="review", off="reflection")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mcp_available", "expected"),
    [(True, "review"), (False, "reflection")],
)
async def test_generate_mcp_branch_is_not_reimplemented(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    mcp_available: bool,
    expected: str,
) -> None:
    """The branch after ``generate`` is the table's route, not a copy.

    The route after ``generate`` depends on ``mcp_available``, and the
    durable path carried a verbatim re-implementation of that branch.
    Inverting the real route separates the two: anything still deriving the
    branch from ``mcp_available`` itself schedules the opposite of the
    live table.
    """
    from co_scientist import workflow_topology

    monkeypatch.setitem(
        workflow_topology.WORKFLOW_ROUTES, "generate", _INVERTED_GENERATE_ROUTE
    )
    run = store.create_run("Durable routing", "standard", "engine", {})
    scheduled = await _commit_node(
        run.id, "generate", isolated_db, mcp_available=mcp_available
    )
    assert scheduled == f"{engine_tasks.NODE_TASK_PREFIX}{expected}"


# The engine-task runtime seam: production wiring and per-task resolution.


def test_production_adapter_is_the_default() -> None:
    """With nothing installed a task resolves the production adapter."""
    assert isinstance(
        engine_tasks_runtime.active(), ProductionEngineTaskRuntime
    )


@pytest.mark.asyncio
async def test_production_adapter_reaches_the_real_collaborators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each production slot calls the collaborator it stands in front of."""
    calls: list[str] = []

    def stub(name: str, result: Any) -> Any:
        def call(*_: Any, **__: Any) -> Any:
            calls.append(name)
            return result

        async def acall(*_: Any, **__: Any) -> Any:
            return call()

        return acall if name in {"screen", "drain"} else call

    monkeypatch.setattr(
        engine_tasks_support, "_generator_and_opts", stub("new", ("g", {}))
    )
    monkeypatch.setattr(
        engine_tasks_support, "_generator_for_restore", stub("restore", "g")
    )
    monkeypatch.setattr(safety, "screen_with_escalation", stub("screen", 1))
    monkeypatch.setattr(
        engine_tasks_node, "_drain_and_persist_final_state", stub("drain", 2)
    )
    adapter = ProductionEngineTaskRuntime()
    anything: Any = object()

    assert adapter.generator_and_opts(anything, None) == ("g", {})
    assert adapter.generator_for_restore(anything, None) == "g"
    screened: Any = await adapter.screen("run", anything, provider="p")
    drained: Any = await adapter.drain_final_state(anything, {}, None)

    assert (screened, drained) == (1, 2)

    assert calls == ["new", "restore", "screen", "drain"]


@pytest.mark.asyncio
async def test_dispatcher_binds_the_adapter_it_resolved_once(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A task keeps the adapter it started with, whatever is installed later."""
    started_with = _install_runtime(monkeypatch)
    replacement = FakeEngineTaskRuntime()
    seen: list[Any] = []

    async def handler(task: Any, **_: Any) -> dict[str, Any]:
        seen.append(engine_tasks_runtime.active())
        monkeypatch.setattr(engine_tasks_runtime, "_installed", replacement)
        seen.append(engine_tasks_runtime.active())
        return {}

    monkeypatch.setitem(
        engine_tasks._ENGINE_TASK_DISPATCH,
        engine_tasks_support.FINALIZE_TASK,
        handler,
    )
    run = store.create_run("Task-level science", "standard", "engine", {})
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=engine_tasks_support.FINALIZE_TASK,
            inputs={},
            idempotency_key="finalize",
        ),
        db_path=isolated_db,
    )

    await engine_tasks.execute_engine_task(task, db_path=isolated_db)

    assert seen == [started_with, started_with]
    installed: Any = engine_tasks_runtime.active()
    assert installed is replacement


# A mid-flight safety halt reaching the run's terminal state (J6).
#
# The engine's safety monitor writes ``safety_blocked`` into the workflow
# state when the run's own meta-review synthesis reaches prohibited content,
# and the durable runtime then schedules finalize instead of more science.
# These tests pin what the app does with that: a halted run must not publish
# a report, must settle as ``blocked`` rather than ``completed``, and must
# say why -- an unexplained blocked run is indistinguishable from a crash.


async def _deterministic_final_screen(
    _run_id: str, subject: ScreenSubject, *_: Any, **__: Any
) -> Any:
    """Stand in for the final escalation, returning its deterministic half."""
    return subject.deterministic


def _seed_halted_finalize(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str, *, halted: bool
) -> Any:
    """Seed a finalize task whose checkpoint carries the monitor's verdict."""
    state = _task_state(run_id)
    state["hypotheses"] = [
        Hypothesis(
            text="Astrocyte lactate accelerates synaptic ATP recovery.",
            literature_grounding=(
                "Astrocyte lactate accelerates synaptic ATP recovery."
            ),
        )
    ]
    if halted:
        state["safety_blocked"] = True
        state["safety_decisions"] = [
            {
                "stage": "research_direction",
                "outcome": "prohibited",
                "reason": "Content matches a prohibited policy rule.",
                "matches": ["engineer smallpox for greater transmiss"],
                "policy_version": "coscientist-safety-v5",
            }
        ]
    _seed_checkpoint(run_id, state, db_path=db_path)
    queued = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=engine_tasks_support.FINALIZE_TASK,
            inputs={},
            idempotency_key="finalize",
        ),
        db_path=db_path,
    )
    task = store.claim_task(
        "finalize-safety-worker", run_id=run_id, db_path=db_path
    )
    assert task is not None and task.id == queued.id
    _patch_restore_generator(monkeypatch, _Generator(state))
    return task


@pytest.mark.asyncio
async def test_a_halted_run_blocks_instead_of_publishing(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The halt is terminal and visible, and no report is released."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    task = _seed_halted_finalize(run.id, monkeypatch, isolated_db, halted=True)

    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert result["status"] == store.RunStatus.BLOCKED.value
    assert store.get_latest_report(run.id, db_path=isolated_db) is None

    settled = store.get_run(run.id, db_path=isolated_db)
    assert settled is not None
    assert settled.status == store.RunStatus.BLOCKED.value
    assert settled.error

    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    monitor = [d for d in decisions if d["stage"] == "research_direction"]
    assert len(monitor) == 1
    assert monitor[0]["decision"] == "block"
    assert monitor[0]["matches"]

    events = store.list_events(run.id, db_path=isolated_db)
    types = [event["type"] for event in events]
    assert "safety.research_direction" in types
    assert "report" not in types


@pytest.mark.asyncio
async def test_an_unhalted_run_still_publishes(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The halt check is the only thing that withholds the report."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    task = _seed_halted_finalize(run.id, monkeypatch, isolated_db, halted=False)
    _install_runtime(monkeypatch).screen = _deterministic_final_screen

    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert result["status"] == store.RunStatus.COMPLETED.value
    assert store.get_latest_report(run.id, db_path=isolated_db) is not None


# Steering consumption: atomic with its commit, and gated to the orchestrator.
#
# Steering was originally acknowledged while the engine opts were built --
# minutes of provider work before the node's checkpoint committed -- so a
# worker that died mid-node left the message flagged applied and its
# guidance nowhere; that crash-atomicity is what the first test below pins.
# A second defect (PARITY ``HITL-STEERING-001``), fixed alongside the newer
# tests here: acknowledging happened at *whichever* node's commit ran next,
# not necessarily the orchestrator -- the one node whose scheduling decision
# actually reads ``state["pending_steering"]`` -- so a message posted while,
# say, proximity was executing was retired before ever reaching a
# scheduling decision. These tests drive the durable node executor with the
# real ``_generator_and_opts``/``build_engine_opts`` (only the generator
# itself is a stand-in) so the acknowledgement path under test is the
# production one.


_STEER = "Prioritise kinase inhibitors over metabolic routes"


def _seed_steered_node_task(
    run_id: str,
    monkeypatch: pytest.MonkeyPatch,
    db_path: str,
    *,
    node: str = "proximity",
) -> store.ScientificTask:
    """Seed a checkpoint, a queued ``node`` task, and one steering message.

    ``proximity`` is the default because it has no durable fan-out, so the
    executor takes the plain execute-then-commit path most of these tests
    are about; a caller passing ``node="orchestrator"`` exercises the one
    node that may actually acknowledge steering.
    """
    state = _task_state(run_id)
    checkpoint_seq = _seed_checkpoint(run_id, state, db_path=db_path)
    store.append_message(
        store.NewMessage(
            run_id=run_id, sender="user", content=_STEER, kind="steering"
        ),
        db_path=db_path,
    )
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}{node}",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"engine.node.{node}:{checkpoint_seq}",
        ),
        db_path=db_path,
    )
    monkeypatch.setattr(
        engine_tasks_support,
        "build_generator",
        lambda *_, **__: _Generator(state),
    )
    leased = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert leased is not None
    return leased


def _record_preferences_and_commit(seen: list[str], *, priority: bool) -> Any:
    """Build an execute_task_node fake that logs preferences then commits.

    ``priority`` sets ``next_task_priority`` on the state before
    returning, required whenever the task under test is the orchestrator
    (``_enqueue_node_portfolio`` reads it only for that node, but reads it
    unconditionally when it does).
    """

    async def _run_node(
        _node: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        seen.append(str(state.get("preferences") or ""))
        if priority:
            state["next_task_priority"] = 90
        return state, "meta_review"

    return _run_node


@pytest.mark.asyncio
async def test_steering_survives_a_crash_before_the_checkpoint_commits(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A node that dies mid-flight leaves its steering claimable again."""
    run = store.create_run("Steering durability", "standard", "engine", {})
    leased = _seed_steered_node_task(run.id, monkeypatch, isolated_db)

    async def _crash(*_: Any, **__: Any) -> Any:
        raise RuntimeError("worker died mid-node")

    _patch_task_node(monkeypatch, _crash)

    with pytest.raises(RuntimeError, match="worker died mid-node"):
        await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    pending = store.get_pending_steering(run.id, db_path=isolated_db)
    assert [message.content for message in pending] == [_STEER]


@pytest.mark.asyncio
async def test_a_non_orchestrator_commit_never_acknowledges_steering(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A committed non-orchestrator node reads but does not retire steering.

    Regression for HITL-STEERING-001: this used to be a valid acknowledging
    boundary (any node's commit). Now only the orchestrator's own commit
    may acknowledge -- see
    ``test_committed_orchestrator_acknowledges_its_steering_exactly_once``
    -- because it is the only node whose scheduling decision reads
    ``state["pending_steering"]`` at all; acknowledging anywhere else
    retires the message before that decision ever runs.
    """
    run = store.create_run("Steering durability", "standard", "engine", {})
    leased = _seed_steered_node_task(run.id, monkeypatch, isolated_db)
    seen: list[str] = []
    _patch_task_node(
        monkeypatch, _record_preferences_and_commit(seen, priority=False)
    )

    await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    assert _STEER in seen[0]
    pending = store.get_pending_steering(run.id, db_path=isolated_db)
    assert [message.content for message in pending] == [_STEER]


@pytest.mark.asyncio
async def test_committed_orchestrator_acknowledges_its_steering_exactly_once(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A committed orchestrator checkpoint retires the steering it read."""
    run = store.create_run("Steering durability", "standard", "engine", {})
    leased = _seed_steered_node_task(
        run.id, monkeypatch, isolated_db, node="orchestrator"
    )
    seen: list[str] = []
    _patch_task_node(
        monkeypatch, _record_preferences_and_commit(seen, priority=True)
    )

    await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    assert _STEER in seen[0]
    assert store.get_pending_steering(run.id, db_path=isolated_db) == []


@pytest.mark.asyncio
async def test_steering_reaches_the_orchestrators_retry_after_a_crash(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crashed orchestrator's retry sees the guidance, then retires it."""
    run = store.create_run("Steering durability", "standard", "engine", {})
    leased = _seed_steered_node_task(
        run.id, monkeypatch, isolated_db, node="orchestrator"
    )
    seen: list[str] = []

    async def _crash_then_commit(
        _node: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        seen.append(str(state.get("preferences") or ""))
        if len(seen) == 1:
            raise RuntimeError("worker died mid-node")
        state["next_task_priority"] = 90
        return state, "meta_review"

    _patch_task_node(monkeypatch, _crash_then_commit)

    with pytest.raises(RuntimeError):
        await engine_tasks.execute_node_task(leased, db_path=isolated_db)
    await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    assert [_STEER in text for text in seen] == [True, True]
    assert store.get_pending_steering(run.id, db_path=isolated_db) == []


@pytest.mark.asyncio
async def test_steering_text_survives_to_the_node_it_was_meant_for(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guidance is not lost the cycle the orchestrator acknowledges it.

    Regression: ``preferences`` used to be rebuilt each restore from only
    the still-*pending* steering, so the very next node after the
    orchestrator's ack (the node the high-priority reschedule is for) saw
    an empty fold and silently lost the guidance it was supposed to
    incorporate. Folding every steering message the run has ever queued
    (applied or not) keeps the text monotone across restores -- checked
    here across two separate durable tasks and checkpoints, not just one.
    """
    run = store.create_run("Steering survives", "standard", "engine", {})
    orchestrator = _seed_steered_node_task(
        run.id, monkeypatch, isolated_db, node="orchestrator"
    )

    async def _orchestrator_run(
        name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        assert name == "orchestrator"
        out = dict(state)
        out["next_task"] = "reflection"
        out["next_task_priority"] = 90
        return out, "reflection"

    _patch_task_node(monkeypatch, _orchestrator_run)
    committed = await engine_tasks.execute_node_task(
        orchestrator, db_path=isolated_db
    )
    assert store.complete_task(
        orchestrator.id, "worker", committed, db_path=isolated_db
    )

    reflection = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert reflection is not None
    assert reflection.task_type == "engine.node.reflection"
    seen: list[str] = []
    _patch_task_node(
        monkeypatch, _record_preferences_and_commit(seen, priority=False)
    )

    await engine_tasks.execute_node_task(reflection, db_path=isolated_db)

    assert seen and "kinase" in seen[0].lower()


# Per-call telemetry attribution for fan-out items and ranking matches.
#
# ``co_scientist.llm.telemetry.scoped_telemetry`` has a single call site on
# the plain node path (``task_runtime.execute_task_node``), which the durable
# fan-out item tasks and ranking match tasks never go through -- they call
# engine functions directly from app-side handlers. These tests pin that the
# fan-out/ranking paths scope telemetry the same way and fold it back into
# the committed run metrics, rather than silently dropping it.


async def _fake_review_with_telemetry(**kwargs: Any) -> HypothesisReview:
    """Stand in for review, recording telemetry the way a real call would."""
    record_call(
        "fixture-model",
        ModelCallStats(calls=1, prompt_tokens=20, completion_tokens=10),
    )
    return HypothesisReview(
        review_summary=f"reviewed {kwargs['hypothesis_text']}",
        scores={"scientific_soundness": 8, "novelty": 8},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="continue",
        overall_score=8.0,
    )


async def _advance_review_node(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> None:
    """Seed a two-hypothesis review node and fan it out."""
    state = _task_state(run_id)
    state["hypotheses"] = [Hypothesis(text="alpha"), Hypothesis(text="beta")]
    checkpoint_seq = _seed_checkpoint(run_id, state)
    node = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}review",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="review-node",
        ),
        db_path=db_path,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True)
    leased = store.claim_task("node", run_id=run_id, db_path=db_path)
    assert leased is not None and leased.id == node.id
    result = await engine_tasks.execute_node_task(leased, db_path=db_path)
    assert store.complete_task(leased.id, "node", result, db_path=db_path)


@pytest.mark.asyncio
async def test_review_fanout_folds_item_telemetry_into_committed_metrics(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Telemetry captured inside a review item survives to the aggregate.

    Every completed review item records one call via
    ``llm.telemetry.record_call``; the aggregate must fold both items'
    usage into the checkpoint's ``metrics.model_usage`` rather than
    dropping it, the way the plain node path already does for
    ``task_runtime.execute_task_node``.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    await _advance_review_node(run.id, monkeypatch, isolated_db)

    import co_scientist.agents.reflection.review as review_module

    monkeypatch.setattr(
        review_module, "review_single_hypothesis", _fake_review_with_telemetry
    )
    first = store.claim_task("child-a", run_id=run.id, db_path=isolated_db)
    second = store.claim_task("child-b", run_id=run.id, db_path=isolated_db)
    assert first is not None and second is not None
    first_result = await engine_tasks_fanout_items.execute_review_item(
        first, db_path=isolated_db
    )
    second_result = await engine_tasks_fanout_items.execute_review_item(
        second, db_path=isolated_db
    )
    assert first_result["model_usage"] == {
        "review::fixture-model": ModelCallStats(
            calls=1, prompt_tokens=20, completion_tokens=10
        ).as_dict()
    }
    assert store.complete_task(
        first.id, "child-a", first_result, db_path=isolated_db
    )
    assert store.complete_task(
        second.id, "child-b", second_result, db_path=isolated_db
    )

    aggregate = store.claim_task(
        "aggregate", run_id=run.id, db_path=isolated_db
    )
    assert aggregate is not None
    aggregate_result = (
        await engine_tasks_fanout_aggregates.execute_review_aggregate(
            aggregate, db_path=isolated_db
        )
    )
    assert store.complete_task(
        aggregate.id, "aggregate", aggregate_result, db_path=isolated_db
    )

    from co_scientist.checkpoint import restore_workflow_state

    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    usage = restored["metrics"].model_usage["review::fixture-model"]
    assert usage["calls"] == 2
    assert usage["prompt_tokens"] == 40
    assert usage["completion_tokens"] == 20


async def _fake_judge_with_telemetry(
    *_: Any, **kwargs: Any
) -> tuple[str, dict[str, Any]]:
    """Stand in for the ranking judge, recording telemetry per matchup."""
    record_call("fixture-model", ModelCallStats(calls=1, prompt_tokens=5))
    return "a", {
        "decision_summary": "A is stronger",
        "confidence_level": "high",
        "debate_turns": int(kwargs["debate_turns"]),
        "debate_transcript": [],
        "judge_model": "fixture-model",
    }


async def _drain_and_finalize_ranking(run_id: str, db_path: str) -> int:
    """Run every match task, then the finalizer; return matches judged."""
    matches = 0
    while True:
        task = store.claim_task(
            f"match-{matches}", run_id=run_id, db_path=db_path
        )
        assert task is not None
        if task.task_type != engine_tasks_support.RANKING_MATCH_TASK:
            break
        result = await engine_tasks_ranking.execute_ranking_match(
            task, db_path=db_path
        )
        assert store.complete_task(
            task.id, f"match-{matches}", result, db_path=db_path
        )
        matches += 1
    assert task.task_type == engine_tasks_support.RANKING_FINALIZE_TASK
    result = await engine_tasks_ranking.execute_ranking_finalize(
        task, db_path=db_path
    )
    assert store.complete_task(
        task.id, f"match-{matches}", result, db_path=db_path
    )
    return matches


@pytest.mark.asyncio
async def test_ranking_matches_fold_telemetry_into_finalized_metrics(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Telemetry from every sequential match survives to the tournament's end.

    No intervening match commit persists a metrics snapshot (each uses
    ``_save_state_and_enqueue_exact``, finding L14's exception) -- the
    running usage has to ride the successor task's inputs the same way
    ``total_llm_calls`` already does, and land in the checkpoint only at
    ``execute_ranking_finalize``.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=4,
            tournament_pairs=8,
            idempotency_key="telemetry-ranking-node",
        ),
        isolated_db,
    )
    import co_scientist.agents.ranking.operations as ranking_module

    monkeypatch.setattr(
        ranking_module, "judge_matchup", _fake_judge_with_telemetry
    )

    # A wave judges several matchups per durable match task, and a small
    # pool exhausts its distinct pairings before the round budget (the same
    # dedup as the "one pair" fix), so neither the requested round budget
    # nor the number of drained match tasks is the matchup count -- only
    # the committed tournament_matchups tally is.
    await _run_ranking_node(run.id, isolated_db)
    await _drain_and_finalize_ranking(run.id, isolated_db)

    from co_scientist.checkpoint import restore_workflow_state

    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    played = len(restored["tournament_matchups"])
    assert played > 1, "fixture must judge more than one matchup"
    usage = restored["metrics"].model_usage["ranking::fixture-model"]
    assert usage["calls"] == played
    assert usage["prompt_tokens"] == played * 5


@pytest.mark.asyncio
async def test_baseline_fake_judge_leaves_no_telemetry(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity check: a judge that never calls ``record_call`` leaves none.

    Pins that the ``ranking::`` usage key only appears when a call is
    actually recorded, so the prior test's presence assertion is
    meaningful rather than an artifact of some other node's usage.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=4,
            tournament_pairs=8,
            idempotency_key="baseline-ranking-node",
        ),
        isolated_db,
    )
    _install_plain_fake_judge(monkeypatch)

    await _run_ranking_node(run.id, isolated_db)
    await _drain_and_finalize_ranking(run.id, isolated_db)

    from co_scientist.checkpoint import restore_workflow_state

    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    assert not any(
        key.startswith("ranking::") for key in restored["metrics"].model_usage
    )
