"""Durable node-level engine task execution and checkpoint commit tests.

Core executor coverage: scientist-input merge, bootstrap, node dispatch,
in-flight pause, and the PARITY-pinned pre-ranking-gate and ranking-match
cases. Sibling ``test_engine_tasks_*.py`` files hold the gate, fan-out,
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
    _seed_checkpoint,
    _task_state,
)


def test_scientist_inputs_merge_into_engine_state_once(
    isolated_db: str,
) -> None:
    """Manual ideas and reviews become typed inputs to later specialists."""
    run = store.create_run("Scientist loop", "standard", "engine", {})
    hypothesis_id = store.add_hypothesis(
        run.id,
        title="Scientist idea",
        statement="A scientist-proposed mechanism",
        created_by_agent="scientist_manual",
        author="researcher",
        db_path=isolated_db,
    )
    store.add_review(
        run.id,
        hypothesis_id,
        "scientist",
        "Scientist verdict: oppose (by researcher)",
        "The proposed control cannot distinguish the mechanism.",
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
async def test_pre_ranking_gate_keeps_unsupported_ideas_rankable() -> None:
    """Unsupported (but non-contradicted) ideas stay rankable.

    Under the rank-and-publish policy the pre-ranking gate only withholds
    contradicted or unsafe ideas; a merely-unsupported idea stays viable (it is
    later published and badged "unverified") rather than being quarantined.
    """
    supported = Hypothesis(
        text="Astrocyte lactate accelerates synaptic ATP recovery."
    )
    unsupported = Hypothesis(
        text="We hypothesize a fictional kinase may alter neuronal aging.",
        literature_grounding=(
            "A fictional kinase completely reverses neuronal aging."
        ),
    )
    for hypothesis in (supported, unsupported):
        hypothesis.review_disposition = "viable"
    state = {
        "hypotheses": [supported, unsupported],
        "articles": [
            Article(
                title="Astrocyte energetics",
                abstract=(
                    "Astrocyte lactate accelerates synaptic ATP recovery."
                ),
                source_id="PMID-1",
            )
        ],
    }

    await engine_tasks._apply_pre_ranking_evidence_gate(state)

    assert supported.review_disposition == "viable"
    assert supported.enrichments["claim_gate"]["decision"] == "allow"
    assert unsupported.review_disposition == "viable"
    assert unsupported.enrichments["claim_gate"]["decision"] == "allow"


@pytest.mark.asyncio
async def test_pre_ranking_gate_records_support_when_evidence_arrives() -> None:
    """A rankable idea's claim graduates to supported once evidence arrives."""
    hypothesis = Hypothesis(
        text="Astrocyte lactate accelerates synaptic ATP recovery.",
        literature_grounding=(
            "Astrocyte lactate accelerates synaptic ATP recovery."
        ),
    )
    hypothesis.review_disposition = "viable"
    state: dict[str, Any] = {"hypotheses": [hypothesis], "articles": []}
    await engine_tasks._apply_pre_ranking_evidence_gate(state)
    # No evidence yet, but a merely-unsupported idea still ranks.
    assert hypothesis.review_disposition == "viable"

    state["articles"] = [
        Article(
            title="Synaptic energetics",
            abstract="Astrocyte lactate accelerates synaptic ATP recovery.",
        )
    ]
    await engine_tasks._apply_pre_ranking_evidence_gate(state)

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.enrichments["claim_gate"]["decision"] == "allow"


def test_evidence_blocked_idea_is_excluded_from_ranking() -> None:
    """A claim-gated idea must not enter the decisive Elo tournament.

    The pre-ranking gate marks an unsupported idea ``evidence_blocked``; the
    ranking scheduler must then leave it out of the tournament, not merely drop
    it at publish time, so its unsupported claim never shifts other ideas' Elo.
    """
    supported = Hypothesis(text="Supported idea.")
    supported.review_disposition = "viable"
    blocked = Hypothesis(text="Unsupported idea.")
    blocked.review_disposition = "evidence_blocked"
    undermined = Hypothesis(text="Undermined idea.")
    undermined.review_disposition = "viable"
    undermined.deep_verification_verdict = "undermined"

    eligible = engine_tasks._ranking_eligible(
        {"hypotheses": [supported, blocked, undermined]}
    )

    assert supported in eligible
    assert blocked not in eligible
    assert undermined not in eligible


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
    offline guard must hold here exactly as it does on the streaming path.
    Without it the contextual model is called for keyless/offline runs, and a
    nondeterministic "uncertain" verdict silently pauses a run that should
    have completed. Patched at ``app.safety.screen_contextual`` -- the seam the
    escalation wrapper itself calls -- so the guard is exercised, not bypassed.
    """
    run = store.create_run(
        "Task-level science",
        "standard",
        "engine",
        {},
        llm_backend="offline",
        db_path=isolated_db,
    )
    engine_tasks.enqueue_bootstrap(run.id, db_path=isolated_db)
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None
    monkeypatch.setattr(
        engine_tasks,
        "_generator_and_opts",
        lambda *_: (_Generator(_task_state(run.id)), {}),
    )

    async def _fail_if_called(*_: Any, **__: Any) -> Any:
        raise AssertionError(
            "offline-backed run escalated to the contextual safety model"
        )

    # Patched in both namespaces: ``app.safety`` is the seam the escalation
    # wrapper calls, and ``engine_tasks`` is where a direct
    # ``screen_contextual`` import rebinds it -- so reintroducing the call fails
    # rather than silently escalating again (raising=False: the name is absent
    # while the code routes through the wrapper, which is the point).
    monkeypatch.setattr(safety, "screen_contextual", _fail_if_called)
    monkeypatch.setattr(
        engine_tasks, "screen_contextual", _fail_if_called, raising=False
    )

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
    bootstrap = engine_tasks.enqueue_bootstrap(run.id, db_path=isolated_db)
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None
    generator = _Generator(_task_state(run.id))
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "screen_with_escalation", _deterministic_screen
    )
    result = await engine_tasks.execute_bootstrap(leased, db_path=isolated_db)
    assert store.complete_task(
        bootstrap.id, "worker", result, db_path=isolated_db
    )
    supervisor = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert supervisor is not None

    async def execute(
        _name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        state["supervisor_guidance"] = {"plan": "fixture"}
        return state, "generate"

    import co_scientist.task_runtime as runtime

    monkeypatch.setattr(runtime, "execute_task_node", execute)
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


@pytest.mark.asyncio
async def test_ranking_matches_are_separate_sequential_checkpointed_tasks(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every Elo match observes the checkpoint committed by its predecessor."""
    from co_scientist.checkpoint import restore_workflow_state

    run = store.create_run("Task-level science", "standard", "engine", {})
    state = _task_state(run.id)
    # Ground each idea so the pre-ranking evidence gate keeps it eligible; the
    # tournament-mechanics assertions below need at least two ranked ideas.
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
    checkpoint_seq = _seed_checkpoint(run.id, state)
    node = store.enqueue_task(
        run.id,
        f"{engine_tasks.NODE_TASK_PREFIX}ranking",
        {"checkpoint_seq": checkpoint_seq},
        idempotency_key="ranking-node",
        db_path=isolated_db,
    )
    generator = _Generator(state)
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "_generator_for_restore", lambda *_: generator
    )

    import co_scientist.agents.ranking.ranking as ranking_module

    async def fake_judge(*_: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        turns = int(kwargs["debate_turns"])
        return "a", {
            "decision_summary": "A is stronger",
            "confidence_level": "high",
            "debate_turns": turns,
            "debate_transcript": [],
            "judge_model": "fixture",
        }

    monkeypatch.setattr(ranking_module, "judge_matchup", fake_judge)
    leased = store.claim_task("ranking", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == node.id
    scheduled = await engine_tasks.execute_node_task(
        leased, db_path=isolated_db
    )
    assert store.complete_task(
        leased.id, "ranking", scheduled, db_path=isolated_db
    )

    # Matchups are judged concurrently inside a wave, but the waves themselves
    # stay sequential: each observes the checkpoint its predecessor committed.
    observed_sequences: list[int] = []
    committed = 0
    index = 0
    while True:
        match = store.claim_task(
            f"match-{index}", run_id=run.id, db_path=isolated_db
        )
        assert match is not None
        if match.task_type != engine_tasks.RANKING_MATCH_TASK:
            finalizer = match
            break
        observed_sequences.append(int(match.inputs["checkpoint_seq"]))
        result = await engine_tasks.execute_ranking_match(
            match, db_path=isolated_db
        )
        if index == 0:
            replay = await engine_tasks.execute_ranking_match(
                match, db_path=isolated_db
            )
            assert replay["replayed"] is True
        committed = int(result["matches_committed"])
        assert store.complete_task(
            match.id, f"match-{index}", result, db_path=isolated_db
        )
        index += 1
    assert observed_sequences == sorted(observed_sequences)
    assert len(set(observed_sequences)) == len(observed_sequences)
    assert committed == 3, "the whole round is judged exactly once"

    result = await engine_tasks.execute_ranking_finalize(
        finalizer, db_path=isolated_db
    )
    assert store.complete_task(
        finalizer.id,
        finalizer.lease_owner or "finalizer",
        result,
        db_path=isolated_db,
    )
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    assert len(restored["tournament_matchups"]) == 3
    assert sum(item.total_matches for item in restored["hypotheses"]) == 6
    tasks = store.list_tasks(run.id, db_path=isolated_db)
    assert sum(
        task.task_type == engine_tasks.RANKING_MATCH_TASK for task in tasks
    ) == len(observed_sequences)
    milestones = [
        message
        for message in store.list_messages(run.id, db_path=isolated_db)
        if message.kind == "milestone"
    ]
    assert [message.content for message in milestones] == [
        "Tournament complete (iteration 0, 3 matches)"
    ]
    events = store.list_events(run.id, db_path=isolated_db)
    ranking_events = [
        e for e in events if e["payload"].get("task") == "ranking"
    ]
    assert len(ranking_events) == 1
    assert ranking_events[0]["payload"]["successor"] == "orchestrator"


@pytest.mark.asyncio
async def test_inflight_pause_checkpoints_exact_successor(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A node finishing after pause commits state but enqueues no next work."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    bootstrap = engine_tasks.enqueue_bootstrap(run.id, db_path=isolated_db)
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None
    generator = _Generator(_task_state(run.id))
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "screen_with_escalation", _deterministic_screen
    )
    result = await engine_tasks.execute_bootstrap(leased, db_path=isolated_db)
    assert store.complete_task(
        bootstrap.id, "worker", result, db_path=isolated_db
    )
    supervisor = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert supervisor is not None

    async def execute(
        _name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        store.update_run_status(run.id, store.RunStatus.PAUSED)
        return state, "generate"

    import co_scientist.task_runtime as runtime

    monkeypatch.setattr(runtime, "execute_task_node", execute)
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
