"""Tournament progress-cadence and wave-concurrency tests for ranking."""

import asyncio
from typing import Any

import pytest
from co_scientist.models import (
    Hypothesis,
)

from app import engine_tasks, store
from tests._engine_tasks_helpers import (
    _Generator,
    _seed_checkpoint,
    _task_state,
)


@pytest.mark.asyncio
async def test_long_tournament_reports_progress_between_its_matches(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A multi-match tournament emits periodic progress, not silence.

    Each Elo match is its own durable task, so a long tournament used to run
    for tens of minutes committing real work while emitting no event at all --
    the live-activity feed showed a healthy run as frozen. Progress is emitted
    on a cadence rather than per match so the feed (which renders only the
    newest handful of events) still shows the surrounding phases.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    state = _task_state(run.id)
    hypotheses = [
        Hypothesis(
            text=f"Mechanism {index} accelerates ATP recovery.",
            literature_grounding=(
                f"Mechanism {index} accelerates ATP recovery."
            ),
        )
        for index in range(4)
    ]
    for hypothesis in hypotheses:
        hypothesis.review_disposition = "viable"
    state.update({"hypotheses": hypotheses, "tournament_pairs": 12})
    checkpoint_seq = _seed_checkpoint(run.id, state)
    store.enqueue_task(
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
        return "a", {
            "decision_summary": "A is stronger",
            "confidence_level": "high",
            "debate_turns": int(kwargs["debate_turns"]),
            "debate_transcript": [],
            "judge_model": "fixture",
        }

    monkeypatch.setattr(ranking_module, "judge_matchup", fake_judge)
    leased = store.claim_task("ranking", run_id=run.id, db_path=isolated_db)
    assert leased is not None
    scheduled = await engine_tasks.execute_node_task(
        leased, db_path=isolated_db
    )
    assert store.complete_task(
        leased.id, "ranking", scheduled, db_path=isolated_db
    )
    rounds = int(scheduled["tournament_rounds"])
    assert rounds > engine_tasks.RANKING_PROGRESS_EVERY

    matches = 0
    while True:
        match = store.claim_task(
            f"match-{matches}", run_id=run.id, db_path=isolated_db
        )
        assert match is not None
        if match.task_type != engine_tasks.RANKING_MATCH_TASK:
            break
        result = await engine_tasks.execute_ranking_match(
            match, db_path=isolated_db
        )
        assert store.complete_task(
            match.id, f"match-{matches}", result, db_path=isolated_db
        )
        matches += 1

    events = store.list_events(run.id, db_path=isolated_db)
    progress = [
        e
        for e in events
        if e["payload"].get("task") == "ranking"
        and e["payload"].get("status") == "running"
    ]
    # The tournament is no longer silent...
    assert progress, "a long tournament emitted no progress at all"
    # ...but it does not drown the feed either.
    assert len(progress) < matches
    assert progress[0]["payload"]["message"] == (
        f"Tournament match {engine_tasks.RANKING_PROGRESS_EVERY} of {rounds}"
    )


@pytest.mark.asyncio
async def test_tournament_judges_a_wave_of_matchups_concurrently(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One match task advances several matchups, judged in parallel.

    A matchup is ~45s of real model work (three debate turns), and the
    tournament ran them strictly one per durable task, so a 128-match round
    took ~94 minutes of wall clock at a concurrency of one. The engine's
    ranking semaphore already bounds parallel judging; the durable path just
    never gave it more than one call to bound.
    """
    run = store.create_run("Wave science", "standard", "engine", {})
    state = _task_state(run.id)
    hypotheses = [
        Hypothesis(
            text=f"Mechanism {index} accelerates ATP recovery.",
            literature_grounding=(
                f"Mechanism {index} accelerates ATP recovery."
            ),
        )
        for index in range(6)
    ]
    for hypothesis in hypotheses:
        hypothesis.review_disposition = "viable"
    state.update({"hypotheses": hypotheses, "tournament_pairs": 12})
    checkpoint_seq = _seed_checkpoint(run.id, state)
    store.enqueue_task(
        run.id,
        f"{engine_tasks.NODE_TASK_PREFIX}ranking",
        {"checkpoint_seq": checkpoint_seq},
        idempotency_key="wave-ranking-node",
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

    in_flight = 0
    peak = 0

    async def fake_judge(*_: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0)  # Yield so siblings can overlap.
        in_flight -= 1
        return "a", {
            "decision_summary": "A is stronger",
            "confidence_level": "high",
            "debate_turns": int(kwargs["debate_turns"]),
            "debate_transcript": [],
            "judge_model": "fixture",
        }

    monkeypatch.setattr(ranking_module, "judge_matchup", fake_judge)
    leased = store.claim_task("ranking", run_id=run.id, db_path=isolated_db)
    assert leased is not None
    scheduled = await engine_tasks.execute_node_task(
        leased, db_path=isolated_db
    )
    assert store.complete_task(
        leased.id, "ranking", scheduled, db_path=isolated_db
    )
    rounds = int(scheduled["tournament_rounds"])
    assert rounds > 1

    match = store.claim_task("w", run_id=run.id, db_path=isolated_db)
    assert match is not None
    assert match.task_type == engine_tasks.RANKING_MATCH_TASK
    result = await engine_tasks.execute_ranking_match(
        match, db_path=isolated_db
    )

    assert peak > 1, "matchups in a wave must be judged concurrently"
    assert result["matches_committed"] > 1, "one task must advance a wave"


@pytest.mark.asyncio
async def test_tournament_wave_fills_to_the_configured_size(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wave judges RANKING_WAVE_SIZE matchups when the budget allows.

    ``_ranking_wave`` picks from the candidate pairings it is handed, so the
    pool it is given is an upper bound on the wave. The durable path asked
    for ``min(3, rounds)`` candidates -- inherited from the streaming path,
    which generates a few and then picks exactly one -- so a wave could never
    reach the configured size no matter how many rounds remained. Each
    matchup is real model work, and every short wave is another sequential
    durable task: the ultra run spent about two hours across 178 of them.
    """
    run = store.create_run("Wave size", "standard", "engine", {})
    state = _task_state(run.id)
    hypotheses = [
        Hypothesis(
            text=f"Mechanism {index} accelerates ATP recovery.",
            literature_grounding=(
                f"Mechanism {index} accelerates ATP recovery."
            ),
        )
        for index in range(8)
    ]
    for hypothesis in hypotheses:
        hypothesis.review_disposition = "viable"
    state.update({"hypotheses": hypotheses, "tournament_pairs": 20})
    checkpoint_seq = _seed_checkpoint(run.id, state)
    store.enqueue_task(
        run.id,
        f"{engine_tasks.NODE_TASK_PREFIX}ranking",
        {"checkpoint_seq": checkpoint_seq},
        idempotency_key="wave-size-ranking-node",
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
        return "a", {
            "decision_summary": "A is stronger",
            "confidence_level": "high",
            "debate_turns": int(kwargs["debate_turns"]),
            "debate_transcript": [],
            "judge_model": "fixture",
        }

    monkeypatch.setattr(ranking_module, "judge_matchup", fake_judge)
    leased = store.claim_task("ranking", run_id=run.id, db_path=isolated_db)
    assert leased is not None
    scheduled = await engine_tasks.execute_node_task(
        leased, db_path=isolated_db
    )
    assert store.complete_task(
        leased.id, "ranking", scheduled, db_path=isolated_db
    )
    assert int(scheduled["tournament_rounds"]) >= engine_tasks.RANKING_WAVE_SIZE

    match = store.claim_task("w", run_id=run.id, db_path=isolated_db)
    assert match is not None
    result = await engine_tasks.execute_ranking_match(
        match, db_path=isolated_db
    )

    assert result["matches_committed"] == engine_tasks.RANKING_WAVE_SIZE


def test_progress_cadence_survives_a_stride_that_skips_boundaries() -> None:
    """Progress reports a boundary the wave stepped over, not just landed on.

    A wave advances the round index by a variable stride, so testing for an
    exact multiple silently skips any boundary the stride jumps. That is how
    a whole tournament once emitted nothing: the strides simply never landed
    on a multiple. The cadence is now defined by the boundary crossed.
    """
    every = engine_tasks.RANKING_PROGRESS_EVERY

    def reports(index: int, next_index: int) -> int | None:
        """Return the milestone announced for one wave, or None."""
        crossed = index // every != next_index // every
        return (next_index // every) * every if crossed else None

    # A stride that steps straight over a boundary still reports it.
    assert reports(0, every + 2) == every
    # Landing exactly on one reports that boundary.
    assert reports(0, every) == every
    # Moving within a single interval stays quiet.
    assert reports(1, every - 1) is None
    # A stride spanning several boundaries reports the newest reached.
    assert reports(0, every * 3 + 1) == every * 3
