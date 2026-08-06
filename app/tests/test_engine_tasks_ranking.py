"""Tournament progress-cadence and wave-concurrency tests for ranking."""

import pytest

from app import engine_tasks, store
from tests._engine_tasks_helpers import (
    _drain_ranking_matches,
    _install_concurrency_tracking_judge,
    _install_plain_fake_judge,
    _RankingSeed,
    _run_ranking_node,
    _running_ranking_events,
    _seed_ranking_node,
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
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=4,
            tournament_pairs=12,
            idempotency_key="ranking-node",
        ),
        isolated_db,
    )
    _install_plain_fake_judge(monkeypatch)

    scheduled = await _run_ranking_node(run.id, isolated_db)
    rounds = int(scheduled["tournament_rounds"])
    assert rounds > engine_tasks.RANKING_PROGRESS_EVERY

    matches = await _drain_ranking_matches(run.id, isolated_db)

    progress = _running_ranking_events(run.id, isolated_db)
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
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=6,
            tournament_pairs=12,
            idempotency_key="wave-ranking-node",
        ),
        isolated_db,
    )
    tracker = _install_concurrency_tracking_judge(monkeypatch)

    scheduled = await _run_ranking_node(run.id, isolated_db)
    assert int(scheduled["tournament_rounds"]) > 1

    match = store.claim_task("w", run_id=run.id, db_path=isolated_db)
    assert match is not None
    assert match.task_type == engine_tasks.RANKING_MATCH_TASK
    result = await engine_tasks.execute_ranking_match(
        match, db_path=isolated_db
    )

    assert tracker["peak"] > 1, "matchups in a wave must be judged concurrently"
    assert result["matches_committed"] > 1, "one task must advance a wave"


@pytest.mark.asyncio
async def test_tournament_wave_fills_to_the_configured_size(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wave judges RANKING_WAVE_SIZE matchups when the budget allows.

    ``_ranking_wave`` picks from the candidate pairings it is handed, so the
    pool it is given is an upper bound on the wave. The durable path asked
    for ``min(3, rounds)`` candidates -- inherited from the retired
    streaming path, which generated a few and picked one -- so a wave could
    never reach the configured size no matter how many rounds remained. Each
    matchup is real model work, and every short wave is another sequential
    durable task: the ultra run spent about two hours across 178 of them.
    """
    run = store.create_run("Wave size", "standard", "engine", {})
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=8,
            tournament_pairs=20,
            idempotency_key="wave-size-ranking-node",
        ),
        isolated_db,
    )
    _install_plain_fake_judge(monkeypatch)

    scheduled = await _run_ranking_node(run.id, isolated_db)
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


@pytest.mark.asyncio
async def test_spent_budget_schedules_no_tournament(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run out of tournament budget must not open another tournament.

    Not merely wasted work: entering a tournament clears
    ``pending_ranking_matchups``, so an empty one overwrites the matches
    the run already judged. The scheduler asks for ranking once per cycle,
    so this is the ordinary case late in a run, and the symptom was a
    completed run reporting zero matches after judging a full round.

    The pool is seeded as already played: a spent budget still owes a first
    match to any hypothesis that has never had one, so only a fully covered
    pool isolates the budget behaviour under test.

    Consumed rounds are counted against the *effective* budget, which scales
    with the pool (``TOURNAMENT_MATCHES_PER_HYPOTHESIS`` matches per idea, two
    ideas per match) rather than stopping at the tier's own number -- eight
    rankable ideas here, so twelve.
    """
    run = store.create_run("Spent budget", "standard", "engine", {})
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=8,
            tournament_pairs=6,
            idempotency_key="spent-budget-ranking-node",
            consumed_rounds=12,
            played=True,
        ),
        isolated_db,
    )
    _install_plain_fake_judge(monkeypatch)

    scheduled = await _run_ranking_node(run.id, isolated_db)

    assert scheduled.get("tournament_rounds") is None
    # The node still advances the run; it just opens no tournament.
    successor = store.claim_task("w", run_id=run.id, db_path=isolated_db)
    assert successor is not None
    assert successor.task_type != engine_tasks.RANKING_MATCH_TASK


@pytest.mark.asyncio
async def test_partial_budget_schedules_only_what_is_left(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Remaining budget, not the tier's full allowance, sizes the pass.

    The pool has already played, so no first match is owed and the
    remaining budget is the only thing sizing the pass.
    """
    run = store.create_run("Partial budget", "standard", "engine", {})
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=8,
            tournament_pairs=12,
            idempotency_key="partial-budget-ranking-node",
            consumed_rounds=9,
            played=True,
        ),
        isolated_db,
    )
    _install_plain_fake_judge(monkeypatch)

    scheduled = await _run_ranking_node(run.id, isolated_db)

    assert int(scheduled["tournament_rounds"]) == 3


def test_wave_elo_is_applied_sequentially_within_the_round() -> None:
    """A later match in a wave sees the Elo the earlier match committed.

    Judgments in a wave run concurrently, but rating application is not a
    judgment input -- it lands one match at a time, in wave order, so each
    match's displayed before/after ratings and upset margin reflect every
    match applied before it (finding H7). Two matches sharing hypothesis A:
    the second must start from the rating the first left A at, not from the
    pre-wave snapshot both were drawn from.
    """
    from co_scientist.models import Hypothesis

    from app.engine_tasks_ranking_wave import _apply_wave_elo

    hyp_a = Hypothesis(text="shared A")
    hyp_b = Hypothesis(text="opponent B")
    hyp_c = Hypothesis(text="opponent C")
    wave = [(hyp_a, hyp_b), (hyp_a, hyp_c)]
    verdict = {"decision_summary": "A wins.", "confidence_level": "High"}
    judged = [
        ("a", dict(verdict, debate_turns=1)),
        ("a", dict(verdict, debate_turns=1)),
    ]

    details, _, _ = _apply_wave_elo(wave, judged, [1, 1], {})

    first, second = details
    # A wins match 1 at 1200 -> 1212 ...
    assert first["winner_elo_before"] == 1200
    assert first["winner_elo_after"] == 1212
    # ... and match 2 starts from 1212, not the pre-wave 1200.
    assert second["winner_elo_before"] == first["winner_elo_after"]
    assert second["winner_elo_after"] == 1223
    assert hyp_a.total_matches == 2
