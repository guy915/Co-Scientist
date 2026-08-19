"""Freezing a run's archive, so a cell becomes a durable identity.

Split from ``test_discovery_tasks`` because this is about the grid's
stability over time rather than about one task's behaviour: until a CVT
run freezes, every read re-clusters and a variant can change cells
because a later one arrived.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest

from app import engine_tasks, store
from app.engine_tasks_variants_schedule import enqueue_discovery_bootstrap
from app.task_worker_outcomes import _handle_task_failure

_GOOD = "import json\njson.dump({'score': 7.0}, open('metrics.json', 'w'))\n"


@pytest.fixture
def db(isolated_db: str) -> str:
    return os.environ["COSCIENTIST_DB_PATH"]


@pytest.fixture
def workspace_root(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("COSCIENTIST_WORKSPACE_DIR", str(tmp_path / "ws"))
    return str(tmp_path / "ws")


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


def _run(config: dict[str, Any]) -> Any:
    run = store.create_run("discovery", "standard", "mock", config)
    store.set_run_config(run.id, config)
    return run


async def _drain(run_id: str, limit: int = 60) -> list[dict[str, Any]]:
    """Runs the real queue until this run has nothing claimable left."""
    results: list[dict[str, Any]] = []
    for _ in range(limit):
        task = store.claim_task("test-worker", run_id=run_id)
        if task is None:
            return results
        try:
            result = await engine_tasks.execute_engine_task(task)
        except Exception as exc:
            _handle_task_failure(task, "test-worker", exc, None)
            continue
        store.complete_task(task.id, "test-worker", result)
        results.append(result)
    raise AssertionError("discovery loop did not settle")


def _stub_growing_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answers every proposal by adding a distinct new module.

    Adding a file rather than editing one, so the patch applies against
    any parent -- an edit keyed to the seed's contents stops matching as
    soon as a child differs from it, and the run then produces too few
    variants to exercise anything.
    """
    from co_scientist.agents.code_evolve import proposal

    counter = {"n": 0}

    async def _call(prompt: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        counter["n"] += 1
        index = counter["n"]
        body = "    " * (index % 3)
        return {
            "patch": (
                f"*** Begin Patch\n*** Add File: helper_{index}.py\n"
                f"+def helper_{index}(n):\n"
                f"+    for i in range(n):\n"
                f"+{body}        n += i\n"
                f"+    return n\n"
                "*** End Patch\n"
            ),
            "rationale": "add a helper",
            "expected_effect": "no change to the score",
        }

    monkeypatch.setattr(proposal, "call_llm_json", _call)


@pytest.mark.asyncio
async def test_a_run_freezes_its_archive_once_it_has_enough_variants(
    db: str, workspace_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Until it freezes, every read re-clusters and a variant can change
    # cells because a later one arrived, so cell ids cannot be compared
    # across generations.
    from app.discovery_spec import grid

    _stub_growing_proposal(monkeypatch)
    run = _run(
        _config(
            _GOOD,
            max_generations=4,
            children_per_generation=3,
            grid={"strategy": "cvt", "cells": 3},
        )
    )
    assert not grid(_run_config_of(run.id)).projection
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)
    frozen = grid(_run_config_of(run.id)).projection
    assert frozen
    assert frozen.columns and frozen.centroids


def _run_config_of(run_id: str) -> dict[str, Any]:
    row = store.get_run(run_id)
    assert row is not None
    return dict(row.config or {})


@pytest.mark.asyncio
async def test_a_frozen_run_keeps_its_cells_still(
    db: str, workspace_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from co_scientist.agents.code_evolve import assign_cells

    from app.discovery_spec import grid

    _stub_growing_proposal(monkeypatch)
    run = _run(
        _config(
            _GOOD,
            max_generations=4,
            children_per_generation=3,
            grid={"strategy": "cvt", "cells": 3},
        )
    )
    enqueue_discovery_bootstrap(run.id)
    await _drain(run.id)
    frozen = grid(_run_config_of(run.id))
    variants = store.list_code_variants(run.id)
    behaviours = [v["behaviour"] for v in variants]
    early = assign_cells(behaviours[:2], frozen)
    whole = assign_cells(behaviours, frozen)[:2]
    assert early == whole


@pytest.mark.asyncio
async def test_a_run_grows_its_tessellation_for_new_behaviour(
    db: str, workspace_root: str
) -> None:
    """A frozen grid still learns, without moving what it placed.

    Freezing is what makes a cell a durable identity across
    generations. Its cost was that behaviour appearing afterwards landed
    in whichever edge cell happened to be nearest -- a run that changed
    character late was niched by the run it used to be.
    """
    from co_scientist.agents.code_evolve import assign_cells

    from app.discovery_spec import grid
    from app.engine_tasks_variants_schedule import freeze_grid_if_ready

    run = _run(
        _config(
            _GOOD,
            max_generations=1,
            descriptors=[{"feature": "source_lines"}],
            grid={"strategy": "cvt", "cells": 4},
        )
    )
    settled = [{"source_lines": float(i)} for i in range(12)]
    variants = [{"behaviour": b} for b in settled]
    config = freeze_grid_if_ready(run.id, variants, run.config)
    frozen = grid(config)
    assert frozen.projection

    novel = [{"source_lines": 9000.0}, {"source_lines": 9001.0}]
    before = assign_cells(novel, frozen)
    grown = grid(
        freeze_grid_if_ready(
            run.id,
            variants + [{"behaviour": b} for b in novel],
            config,
        )
    )
    # The new behaviour is its own kind now, and every variant that was
    # already placed is still where it was.
    assert assign_cells(novel, grown) != before
    assert assign_cells(settled, grown) == assign_cells(settled, frozen)
