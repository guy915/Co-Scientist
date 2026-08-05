"""Durable node-level engine task execution and checkpoint commit tests.

Core executor coverage: scientist-input merge, bootstrap, node dispatch,
in-flight pause, and the PARITY-pinned ranking-match case. Sibling
``test_engine_tasks_*.py`` files hold the pre-ranking-gate, gate, fan-out,
ranking-tournament, and dispatch clusters.
"""

from typing import Any

import pytest
from co_scientist.models import (
    Article,
    Hypothesis,
)

from app import engine_tasks, safety, store, task_worker
from tests._engine_tasks_helpers import (
    _deterministic_screen,
    _Generator,
    _install_plain_fake_judge,
    _milestones,
    _patch_generator,
    _patch_task_node,
    _seed_checkpoint,
    _task_events,
    _task_state,
)


def _forbid_contextual_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail the run if it escalates to the contextual safety model.

    Patched in both namespaces: ``app.safety`` is the seam the escalation
    wrapper calls, and ``engine_tasks`` is where a direct ``screen_contextual``
    import rebinds it -- so reintroducing the call fails rather than silently
    escalating again (raising=False: the name is absent while the code routes
    through the wrapper, which is the point).
    """

    async def _fail_if_called(*_: Any, **__: Any) -> Any:
        raise AssertionError(
            "offline-backed run escalated to the contextual safety model"
        )

    monkeypatch.setattr(safety, "screen_contextual", _fail_if_called)
    monkeypatch.setattr(
        engine_tasks, "screen_contextual", _fail_if_called, raising=False
    )


async def _advance_to_supervisor(
    run_id: str,
    monkeypatch: pytest.MonkeyPatch,
    db_path: str,
) -> Any:
    """Bootstrap ``run_id`` and return its claimed supervisor node task."""
    bootstrap = engine_tasks.enqueue_bootstrap(run_id, db_path=db_path)
    leased = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert leased is not None
    generator = _Generator(_task_state(run_id))
    _patch_generator(monkeypatch, generator, screen=True)
    result = await engine_tasks.execute_bootstrap(leased, db_path=db_path)
    assert store.complete_task(bootstrap.id, "worker", result, db_path=db_path)
    supervisor = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert supervisor is not None
    return supervisor


def test_scientist_inputs_merge_into_engine_state_once(
    isolated_db: str,
) -> None:
    """Manual ideas and reviews become typed inputs to later specialists."""
    run = store.create_run("Scientist loop", "standard", "engine", {})
    hypothesis_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Scientist idea",
            statement="A scientist-proposed mechanism",
            created_by_agent="scientist_manual",
            author="researcher",
        ),
        db_path=isolated_db,
    )
    store.add_review(
        store.NewReview(
            run_id=run.id,
            hypothesis_id=hypothesis_id,
            reviewer_agent="scientist",
            summary="Scientist verdict: oppose (by researcher)",
            critique="The proposed control cannot distinguish the mechanism.",
        ),
        db_path=isolated_db,
    )
    state = _task_state(run.id)

    engine_tasks._merge_scientist_inputs(state, run.id, isolated_db)
    engine_tasks._merge_scientist_inputs(state, run.id, isolated_db)

    merged = state["hypotheses"]
    assert [hypothesis.id for hypothesis in merged] == [hypothesis_id]
    assert merged[0].origin.value == "scientist_manual"
    assert len(merged[0].reviews) == 1
    assert merged[0].reviews[0].overall_score == 20
    assert "cannot distinguish" in merged[0].reviews[0].constructive_feedback


def test_scientist_input_reopens_completed_engine_run(isolated_db: str) -> None:
    """A completed engine report can continue from its durable checkpoint."""
    run = store.create_run("Continuation", "standard", "engine", {})
    checkpoint_seq = _seed_checkpoint(
        run.id,
        _task_state(run.id),
        stage="engine_task:final",
        db_path=isolated_db,
    )
    store.update_run_status(
        run.id, store.RunStatus.COMPLETED, db_path=isolated_db
    )

    task = engine_tasks.enqueue_scientist_continuation(
        run.id, 42, db_path=isolated_db
    )

    assert task is not None
    assert task.task_type == "engine.node.orchestrator"
    assert task.inputs["checkpoint_seq"] == checkpoint_seq
    assert task.priority == 100
    reopened = store.get_run(run.id, db_path=isolated_db)
    assert reopened is not None and reopened.status == "queued"


@pytest.mark.asyncio
async def test_bootstrap_commits_state_and_enqueues_supervisor(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = store.create_run("Task-level science", "standard", "engine", {})
    bootstrap = engine_tasks.enqueue_bootstrap(run.id, db_path=isolated_db)
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == bootstrap.id
    generator = _Generator(_task_state(run.id))
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "screen_with_escalation", _deterministic_screen
    )

    result = await engine_tasks.execute_bootstrap(leased, db_path=isolated_db)
    assert store.complete_task(leased.id, "worker", result, db_path=isolated_db)

    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None and checkpoint["seq"] == 1
    tasks = store.list_tasks(run.id, db_path=isolated_db)
    assert [task.task_type for task in tasks] == [
        "engine.bootstrap",
        "engine.node.supervisor",
    ]


@pytest.mark.asyncio
async def test_bootstrap_never_escalates_an_offline_backed_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An offline-backed run's intake gate makes no contextual model call.

    The durable bootstrap screens through ``screen_with_escalation``, whose
    offline guard must hold at that boundary. Without it the contextual model
    is called for keyless/offline runs, and a nondeterministic "uncertain"
    verdict silently pauses a run that should have completed. Patched at
    ``app.safety.screen_contextual`` -- the seam the escalation wrapper itself
    calls -- so the guard is exercised, not bypassed.
    """
    run = store.create_run(
        "Task-level science",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(llm_backend="offline", db_path=isolated_db),
    )
    engine_tasks.enqueue_bootstrap(run.id, db_path=isolated_db)
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None
    _patch_generator(monkeypatch, _Generator(_task_state(run.id)))
    _forbid_contextual_escalation(monkeypatch)

    result = await engine_tasks.execute_bootstrap(leased, db_path=isolated_db)

    # The success path returns the committed checkpoint, not a status verdict;
    # a withheld/paused run would carry one instead of enqueuing a successor.
    assert result.get("status") != "withheld"
    assert "checkpoint_seq" in result
    refreshed = store.get_run(run.id, db_path=isolated_db)
    assert refreshed is not None and refreshed.status != "paused"


@pytest.mark.asyncio
async def test_node_task_commits_once_and_schedules_successor(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = store.create_run("Task-level science", "standard", "engine", {})
    supervisor = await _advance_to_supervisor(run.id, monkeypatch, isolated_db)

    async def execute(
        _name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        state["supervisor_guidance"] = {"plan": "fixture"}
        return state, "generate"

    _patch_task_node(monkeypatch, execute)
    committed = await engine_tasks.execute_node_task(
        supervisor, db_path=isolated_db
    )
    assert store.complete_task(
        supervisor.id, "worker", committed, db_path=isolated_db
    )
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None and checkpoint["seq"] == 2
    assert [
        task.task_type for task in store.list_tasks(run.id, db_path=isolated_db)
    ] == [
        "engine.bootstrap",
        "engine.node.supervisor",
        "engine.node.generate",
    ]


def _seed_ranking_state(run_id: str, db_path: str) -> tuple[Any, _Generator]:
    """Seed a 3-idea ranking node whose grounded ideas survive the gate."""
    state = _task_state(run_id)
    hypotheses = [
        Hypothesis(
            text=f"Mechanism {index} accelerates ATP recovery.",
            literature_grounding=(
                f"Mechanism {index} accelerates ATP recovery."
            ),
        )
        for index in range(3)
    ]
    for hypothesis in hypotheses:
        hypothesis.review_disposition = "viable"
    state.update(
        {
            "hypotheses": hypotheses,
            "tournament_pairs": 3,
            "articles": [
                Article(
                    title=f"Energetics {index}",
                    abstract=(f"Mechanism {index} accelerates ATP recovery."),
                    source_id=f"PMID-{index}",
                )
                for index in range(3)
            ],
        }
    )
    checkpoint_seq = _seed_checkpoint(run_id, state)
    node = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}ranking",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="ranking-node",
        ),
        db_path=db_path,
    )
    return node, _Generator(state)


def _patch_ranking_judge(
    monkeypatch: pytest.MonkeyPatch, generator: _Generator
) -> None:
    """Route the generator seams and stub the pairwise Elo judge."""
    _patch_generator(monkeypatch, generator, restore=True)
    _install_plain_fake_judge(monkeypatch)


async def _drain_ranking_matches(
    run_id: str, db_path: str
) -> tuple[Any, list[int], int]:
    """Claim and judge each match wave in order; return the finalizer.

    Matchups are judged concurrently inside a wave, but the waves themselves
    stay sequential: each observes the checkpoint its predecessor committed.
    The first match is replayed to prove idempotent re-execution.
    """
    observed_sequences: list[int] = []
    committed = 0
    index = 0
    while True:
        match = store.claim_task(
            f"match-{index}", run_id=run_id, db_path=db_path
        )
        assert match is not None
        if match.task_type != engine_tasks.RANKING_MATCH_TASK:
            return match, observed_sequences, committed
        observed_sequences.append(int(match.inputs["checkpoint_seq"]))
        result = await engine_tasks.execute_ranking_match(
            match, db_path=db_path
        )
        if index == 0:
            replay = await engine_tasks.execute_ranking_match(
                match, db_path=db_path
            )
            assert replay["replayed"] is True
        committed = int(result["matches_committed"])
        assert store.complete_task(
            match.id, f"match-{index}", result, db_path=db_path
        )
        index += 1


async def _finalize_and_assert_ranking(
    finalizer: Any,
    run_id: str,
    observed_sequences: list[int],
    db_path: str,
) -> None:
    """Run the ranking finalizer and pin the committed tournament state."""
    from co_scientist.checkpoint import restore_workflow_state

    result = await engine_tasks.execute_ranking_finalize(
        finalizer, db_path=db_path
    )
    assert store.complete_task(
        finalizer.id,
        finalizer.lease_owner or "finalizer",
        result,
        db_path=db_path,
    )
    checkpoint = store.get_latest_checkpoint(run_id, db_path=db_path)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    assert len(restored["tournament_matchups"]) == 3
    assert sum(item.total_matches for item in restored["hypotheses"]) == 6
    tasks = store.list_tasks(run_id, db_path=db_path)
    assert sum(
        task.task_type == engine_tasks.RANKING_MATCH_TASK for task in tasks
    ) == len(observed_sequences)
    assert _milestones(run_id, db_path=db_path) == [
        "Tournament complete (iteration 0, 3 matches)"
    ]
    ranking_events = _task_events(run_id, "ranking", db_path=db_path)
    assert len(ranking_events) == 1
    assert ranking_events[0]["payload"]["successor"] == "orchestrator"


@pytest.mark.asyncio
async def test_ranking_matches_are_separate_sequential_checkpointed_tasks(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every Elo match observes the checkpoint committed by its predecessor."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    node, generator = _seed_ranking_state(run.id, isolated_db)
    _patch_ranking_judge(monkeypatch, generator)
    leased = store.claim_task("ranking", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == node.id
    scheduled = await engine_tasks.execute_node_task(
        leased, db_path=isolated_db
    )
    assert store.complete_task(
        leased.id, "ranking", scheduled, db_path=isolated_db
    )

    finalizer, observed_sequences, committed = await _drain_ranking_matches(
        run.id, isolated_db
    )
    assert observed_sequences == sorted(observed_sequences)
    assert len(set(observed_sequences)) == len(observed_sequences)
    assert committed == 3, "the whole round is judged exactly once"

    await _finalize_and_assert_ranking(
        finalizer, run.id, observed_sequences, isolated_db
    )


@pytest.mark.asyncio
async def test_inflight_pause_checkpoints_exact_successor(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A node finishing after pause commits state but enqueues no next work."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    supervisor = await _advance_to_supervisor(run.id, monkeypatch, isolated_db)

    async def execute(
        _name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        store.update_run_status(run.id, store.RunStatus.PAUSED)
        return state, "generate"

    _patch_task_node(monkeypatch, execute)
    paused = await engine_tasks.execute_node_task(
        supervisor, db_path=isolated_db
    )
    assert store.complete_task(
        supervisor.id, "worker", paused, db_path=isolated_db
    )
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["state"]["resume_successor"] == "engine.node.generate"
    assert len(store.list_tasks(run.id, db_path=isolated_db)) == 2

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )
    assert resumed.task_type == "engine.node.generate"
