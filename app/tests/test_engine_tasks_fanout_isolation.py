"""One failed item must not discard the batch it was gathered with.

The durable ranking wave judges several matchups against one Elo snapshot
under a single ``asyncio.gather``. Without isolation the first judge to
raise cancels its siblings and fails the whole wave task, so a run loses
every comparison the wave had already paid for and re-judges them on the
retry -- and burns the wave's retry budget on a fault that is per-matchup,
not per-wave.
"""

from typing import Any

import pytest

from app import store
from tests._engine_tasks_helpers import (
    _drain_ranking_matches,
    _RankingSeed,
    _run_ranking_node,
    _seed_ranking_node,
)


def _install_judge_failing_once(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int]:
    """Patch ``judge_matchup`` so its first call raises, the rest succeed.

    Returns a counter box whose ``calls`` key records every invocation, so
    a test can tell an isolated failure from a cancelled sibling.
    """
    import co_scientist.agents.ranking.ranking as ranking_module

    box = {"calls": 0}

    async def fake_judge(*_: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        box["calls"] += 1
        if box["calls"] == 1:
            raise RuntimeError("judge provider refused this matchup")
        return "a", {
            "decision_summary": "A is stronger",
            "confidence_level": "high",
            "debate_turns": int(kwargs["debate_turns"]),
            "debate_transcript": [],
            "judge_model": "fixture",
        }

    monkeypatch.setattr(ranking_module, "judge_matchup", fake_judge)
    return box


@pytest.mark.asyncio
async def test_one_failed_matchup_leaves_its_wave_siblings_committed(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raising judge costs its own matchup, not the whole tournament."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=6,
            tournament_pairs=8,
            idempotency_key="ranking-isolation",
        ),
        isolated_db,
    )
    box = _install_judge_failing_once(monkeypatch)

    scheduled = await _run_ranking_node(run.id, isolated_db)
    await _drain_ranking_matches(run.id, isolated_db)

    rounds = int(scheduled["tournament_rounds"])
    assert box["calls"] == rounds, "siblings of the failed matchup were lost"
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    committed = checkpoint["state"]["state"]["pending_ranking_matchups"]
    assert len(committed) == rounds - 1
    tasks = store.list_tasks(run.id, db_path=isolated_db)
    assert [task.status for task in tasks if task.status == "failed"] == []
