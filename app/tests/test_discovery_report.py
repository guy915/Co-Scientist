"""The report a discovery run leaves behind.

Two claims are load-bearing here and neither is about formatting. The
report must not borrow the hypothesis report's vocabulary, because every
count in that payload is named for something a discovery run does not
have. And publishing must not be able to fail the run: the search is
already over and every variant is already durable by the time this
happens, so a formatting bug that raised would retry a finished search.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from typing import Any

import pytest

from app import discovery_report, engine_tasks, store
from app.engine_tasks_variants_schedule import enqueue_discovery_bootstrap

_GOOD = "import json\njson.dump({'score': 7.0}, open('metrics.json', 'w'))\n"
_CRASHES = "raise RuntimeError('boom')\n"


def _config(program: str, **overrides: Any) -> dict[str, Any]:
    discovery: dict[str, Any] = {
        "objective": {"metric": "score", "direction": "maximize"},
        "stages": [
            {
                "name": "run",
                "argv": [sys.executable, "main.py"],
                "timeout_seconds": 60,
            }
        ],
        "seed_source": {"main.py": program},
    }
    discovery.update(overrides)
    return {"discovery": discovery}


@pytest.fixture
def workspace_root(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("COSCIENTIST_WORKSPACE_DIR", str(tmp_path / "ws"))
    return str(tmp_path / "ws")


@pytest.fixture
def db(isolated_db: str) -> str:
    return os.environ["COSCIENTIST_DB_PATH"]


def _run(config: dict[str, Any]) -> Any:
    run = store.create_run("beat the baseline", "standard", "mock", config)
    store.set_run_config(run.id, config)
    return run


async def _drain(run_id: str, limit: int = 60) -> None:
    for _ in range(limit):
        task = store.claim_task("test-worker", run_id=run_id)
        if task is None:
            return
        result = await engine_tasks.execute_engine_task(task)
        store.complete_task(task.id, "test-worker", result)
    raise AssertionError("discovery loop did not settle")


@pytest.mark.asyncio
async def test_a_finished_run_publishes_a_report(
    db: str, workspace_root: str
) -> None:
    run = _run(_config(_GOOD, max_generations=1))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)

    assert store.get_run(run.id).status == "completed"
    report = store.get_latest_report(run.id)
    assert report is not None
    payload = report["payload"]
    assert payload["report_kind"] == "discovery"
    assert payload["variant_count"] == 1
    assert payload["best_fitness"] == 7.0
    assert "beat the baseline" in store.read_report_markdown(run.id)


@pytest.mark.asyncio
async def test_the_payload_borrows_no_hypothesis_counts(
    db: str, workspace_root: str
) -> None:
    # Reusing those keys would leave every tab reading a number named
    # for something this run never produced.
    run = _run(_config(_GOOD, max_generations=1))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)

    payload = store.get_latest_report(run.id)["payload"]
    for borrowed in (
        "hypothesis_count",
        "idea_count",
        "verified_count",
        "leaderboard",
        "idea_buckets",
        "match_count",
    ):
        assert borrowed not in payload


@pytest.mark.asyncio
async def test_a_report_that_cannot_be_built_still_completes_the_run(
    db: str, workspace_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The search is over and every variant is durable by now, so raising
    # here would retry a finished run rather than recover anything.
    def _explode(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("bad format string")

    monkeypatch.setattr(discovery_report, "build_markdown", _explode)
    run = _run(_config(_GOOD, max_generations=1))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)

    assert store.get_run(run.id).status == "completed"
    assert store.get_latest_report(run.id) is None


@pytest.mark.asyncio
async def test_every_evaluated_variant_is_narrated(
    db: str, workspace_root: str
) -> None:
    # The loop is three durable tasks and none of them emitted, so a
    # discovery run streamed nothing at all: the live activity log sat
    # empty for its whole duration and a working search was
    # indistinguishable from a stalled one.
    run = _run(_config(_GOOD, max_generations=1))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)

    events = store.list_events(run.id)
    variants = [event for event in events if event["type"] == "discovery"]
    assert len(variants) == 1
    assert variants[0]["payload"]["ordinal"] == 1
    assert variants[0]["payload"]["fitness"] == 7.0
    assert variants[0]["payload"]["operator"] == "seed"


@pytest.mark.asyncio
async def test_a_crashed_variant_is_narrated_too(
    db: str, workspace_root: str
) -> None:
    # Silence on failure is the reading the log must not give: a run
    # whose every attempt crashes is still a run making progress.
    run = _run(_config(_CRASHES, max_generations=1))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)

    narrated = [
        e for e in store.list_events(run.id) if e["type"] == "discovery"
    ]
    assert narrated[0]["payload"]["status"] == "failed"
    assert narrated[0]["payload"]["fitness"] is None


@pytest.mark.asyncio
async def test_a_failing_event_write_does_not_retry_the_finished_run(
    db: str, workspace_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The event write is a write like any other, so a full volume fails
    # it. Raising past an already-saved report would retry the finished
    # aggregate and append another report row on every attempt.
    def _explode(*args: Any, **kwargs: Any) -> int:
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(store, "append_event", _explode)
    run = _run(_config(_GOOD, max_generations=1))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)

    assert store.get_run(run.id).status == "completed"
    assert store.get_latest_report(run.id) is not None


@pytest.mark.asyncio
async def test_failed_attempts_keep_their_place_in_the_report(
    db: str, workspace_root: str
) -> None:
    # How many attempts a result took is only readable if what went
    # nowhere is still numbered in the sequence.
    run = _run(_config(_CRASHES, max_generations=1))
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)

    markdown = store.read_report_markdown(run.id)
    assert "| 1 | seed | failed | — |" in markdown
    assert "No attempt produced a usable score." in markdown


def _variant(ordinal: int, fitness: float | None, **extra: Any) -> Any:
    variant: dict[str, Any] = {
        "id": f"v{ordinal}",
        "ordinal": ordinal,
        "generation": ordinal - 1,
        "operator": "rewrite",
        "status": "scored",
        "fitness": fitness,
        "rationale": "",
        "source": {"main.py": "pass\n"},
        "objective_values": [fitness],
        "behaviour": {},
        "is_best_so_far": False,
    }
    variant.update(extra)
    return variant


def _fake_run(config: dict[str, Any]) -> Any:
    return store.RunRow(
        id="r1",
        research_goal="beat the baseline",
        profile="standard",
        status="completed",
        provider="mock",
        config=config,
        client_id="c1",
        created_at=0.0,
        updated_at=0.0,
        completed_at=None,
        error=None,
    )


def test_the_trade_off_section_appears_only_with_several_objectives() -> None:
    single = _config("pass\n")
    markdown = discovery_report.build_markdown(
        _fake_run(single), [_variant(1, 3.0)], (1, 1.0)
    )
    assert "The trade-off" not in markdown

    multi = _config("pass\n")
    multi["discovery"]["objectives"] = [
        {"metric": "score", "direction": "maximize"},
        {"metric": "seconds", "direction": "minimize"},
    ]
    del multi["discovery"]["objective"]
    markdown = discovery_report.build_markdown(
        _fake_run(multi),
        # Stored sign-corrected, so 1.5 seconds is held as -1.5.
        [_variant(1, 3.0, objective_values=[3.0, -1.5])],
        (1, 1.0),
    )
    assert "The trade-off" in markdown
    assert "`seconds` ↓" in markdown
    assert "| 1 | 3.0 | 1.5 |" in markdown


def test_a_minimized_metric_reads_in_its_own_units() -> None:
    # Scores are stored sign-corrected so higher is always better, which
    # holds a minimized metric negated. Printed straight, 1.9 seconds
    # reports as -1.9 -- a number matching nothing the program produced.
    config = _config("pass\n")
    config["discovery"]["objective"] = {
        "metric": "seconds",
        "direction": "minimize",
    }
    markdown = discovery_report.build_markdown(
        _fake_run(config), [_variant(1, -1.9)], (1, 1.0)
    )
    assert "scored 1.9 via" in markdown
    assert "-1.9" not in markdown


def test_one_attempt_is_not_reported_as_one_attempts() -> None:
    markdown = discovery_report.build_markdown(
        _fake_run(_config("pass\n")), [_variant(1, 3.0)], (1, 1.0)
    )
    assert "1 attempt across" in markdown


def test_a_lopsided_run_is_called_out_rather_than_flattered() -> None:
    # Twelve cells with everything piled into one reads as thorough
    # unless the evenness is said out loud.
    even = discovery_report.build_markdown(
        _fake_run(_config("pass\n")), [_variant(1, 3.0)], (4, 0.95)
    )
    assert "explored less" not in even

    lopsided = discovery_report.build_markdown(
        _fake_run(_config("pass\n")), [_variant(1, 3.0)], (4, 0.2)
    )
    assert "explored less" in lopsided


def test_a_long_program_is_truncated_rather_than_dumped_whole() -> None:
    big = "x = 1\n" * 4000
    markdown = discovery_report.build_markdown(
        _fake_run(_config("pass\n")),
        [_variant(1, 3.0, source={"main.py": big})],
        (1, 1.0),
    )
    assert len(markdown) < len(big)
    assert "truncated" in markdown
    assert "more file(s) omitted" not in markdown


def test_an_unreadable_spec_still_yields_a_report() -> None:
    # The spec is validated when the run starts, but a report built from
    # a config edited since must still say what happened.
    markdown = discovery_report.build_markdown(
        _fake_run({"discovery": {"nonsense": True}}),
        [_variant(1, 3.0)],
        (1, 1.0),
    )
    assert "Every attempt" in markdown
    assert json.dumps({"ok": True})  # keeps the import honest
