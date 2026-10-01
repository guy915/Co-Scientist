"""Startup seeding for complete, curated demo runs.

Creates three browseable examples for newcomers. The default scenarios are
curated, illustrative fixtures with realistic run artifacts; ad-hoc seed
calls retain the real offline-engine fallback used by tests and developers.

This module owns which runs are seeded and when. The curated content itself
lives in siblings -- goal-detail lists in ``seed_planning``, the derived-row
writers in ``seed_scenario``, and the terminal synthesis payloads in
``seed_overview`` -- the moved names callers and tests use re-exported here
so ``app.seed`` stays their import and monkeypatch surface.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app import store, task_worker
from app.demo_seed_data import DEMO_SCENARIOS, DEMO_SEED_VERSION
from app.litellm_shutdown import run_in_scoped_loop
from app.run_modes import resolved_run_config, setup_config
from app.seed_planning import (
    _scenario_planning_lists as _scenario_planning_lists,
)
from app.seed_scenario import (
    _seed_curated_scenario as _seed_curated_scenario,
)
from app.store import DEMO_CLIENT_ID, RunRow

logger = logging.getLogger(__name__)

# The fallback engine path stays intentionally small. Curated scenarios do
# not consume this budget, but direct callers can still ask to seed an
# arbitrary goal through the deterministic engine.
_DEMO_TIER = "express"

_DEMO_GOALS: list[str] = [
    "What mechanisms drive antibiotic resistance in Staphylococcus aureus "
    "biofilms, and which metabolic pathways could be targeted to restore "
    "susceptibility?",
    "How does synaptic pruning in the prefrontal cortex contribute to "
    "cognitive flexibility during adolescent development?",
    "What are the key molecular regulators of ferroptosis in pancreatic cancer "
    "cells, and how might their modulation enhance chemotherapy sensitivity?",
]


def _build_demo_run_config(goal: str) -> dict[str, Any]:
    """Build the resolved run config for one demo goal.

    The marker allows deployed instances to replace an older thin demo with
    the current curated artifact bundle exactly once.
    """
    scenario = DEMO_SCENARIOS.get(goal)
    config = resolved_run_config(
        {
            "setup": setup_config(
                research_goal=goal,
                tier="standard",
                focus="balance",
                lists=_scenario_planning_lists(scenario),
            ),
            "enable_literature_review": False,
            "llm_backend": "offline",
        }
    )
    config["demo_seed_version"] = DEMO_SEED_VERSION
    return config


def _ensure_demo_run_row(
    goal: str,
    run: RunRow | None,
    config: dict[str, Any],
    db_path: str | None,
) -> RunRow:
    """Return `run`, creating the demo run row first if one doesn't exist."""
    if run is not None:
        return run
    scenario = DEMO_SCENARIOS.get(goal)
    return store.create_run(
        goal,
        _DEMO_TIER,
        "engine",
        config,
        store.RunCreateOptions(
            client_id=DEMO_CLIENT_ID,
            title=scenario.title if scenario else None,
            llm_backend="offline",
            db_path=db_path,
        ),
    )


def _drive_demo_run(run_id: str, db_path: str | None) -> None:
    """Drain one demo run's durable task chain to completion.

    Runs a bounded worker cohort on its own event loop, exactly as the
    embedded API worker does for a real ``POST /start`` (see
    ``runs.lifecycle._enqueue_workflow_and_maybe_launch_worker``). The cohort
    returns once the run has no ready task left -- i.e. once it has reached a
    terminal state and persisted its report -- so the caller can rely on the
    demo run being complete when this returns.
    """
    policy = task_worker.WorkerPolicy(db_path=db_path)
    run_in_scoped_loop(
        task_worker.run_run_worker_pool(
            run_id,
            f"demo-seed:{run_id[:8]}",
            policy=policy,
        )
    )


def _scenario_report_is_current(run: RunRow, db_path: str | None) -> bool:
    """Return whether a curated scenario has the current artifact revision."""
    report = store.get_latest_report(run.id, db_path=db_path)
    setup = run.config.get("setup") if isinstance(run.config, dict) else None
    return bool(
        report
        and report["payload"].get("demo_seed_version") == DEMO_SEED_VERSION
        and run.config.get("demo_seed_version") == DEMO_SEED_VERSION
        and isinstance(setup, dict)
        and setup.get("requirements")
        and setup.get("attributes")
    )


async def _seed_demo_run(
    goal: str,
    run: RunRow | None,
    db_path: str | None,
) -> None:
    """Create one curated default scenario or an offline-engine fallback.

    Known default goals receive a complete curated fixture. Other callers use
    the existing durable, deterministic engine path, keeping a realistic
    exercise route available without making product examples depend on it.

    Args:
        goal: The demo research goal to seed.
        run: The existing run row for this goal, or None to create one.
        db_path: Optional override for the SQLite database path.
    """
    config = _build_demo_run_config(goal)
    run = _ensure_demo_run_row(goal, run, config, db_path)
    scenario = DEMO_SCENARIOS.get(goal)
    if scenario is not None:
        # Re-seeded demos may predate the setup fields shown in Goal Details.
        # Keep their row configuration in sync with newly created demo rows.
        store.set_run_config(run.id, config, db_path=db_path)
        await _seed_curated_scenario(run, scenario, db_path)
        logger.info("Seeded curated demo run %s (%.60s…)", run.id[:8], goal)
        return
    task_worker.enqueue_run_workflow(run.id, db_path=db_path)
    # Run the cohort on its own loop/thread (mirroring the embedded worker)
    # and await it, so seeding blocks until the run is complete rather than
    # racing startup.
    await asyncio.to_thread(_drive_demo_run, run.id, db_path)
    logger.info("Seeded offline engine demo run %s (%.60s…)", run.id[:8], goal)


def _runs_by_goal(runs: list[RunRow]) -> dict[str, RunRow]:
    """Index demo run rows by their research goal for lookup."""
    return {r.research_goal: r for r in runs}


def _has_readable_report(run: RunRow, db_path: str | None) -> bool:
    """True if `run` already has a persisted, readable report markdown."""
    return store.read_report_markdown(run.id, db_path=db_path) is not None


async def _seed_or_reseed_demo_run(
    goal: str,
    run: RunRow | None,
    db_path: str | None,
) -> None:
    """Seed `goal`, skipping an existing demo at the current revision.

    A failed seed must not take down app startup; it is logged and swallowed
    here so the caller can move on to the next demo goal.
    """
    if run is not None:
        scenario = DEMO_SCENARIOS.get(goal)
        current = (
            _scenario_report_is_current(run, db_path)
            if scenario is not None
            else _has_readable_report(run, db_path)
        )
        if current:
            logger.info(
                "demo run %s already has a report, skipping", run.id[:8]
            )
            return
        logger.info(
            "demo run %s exists but has no readable report; re-seeding",
            run.id[:8],
        )
    try:
        await _seed_demo_run(goal, run, db_path)
    except Exception:
        logger.exception("Failed to seed demo run for goal: %.60s", goal)


async def seed_demo_runs(db_path: str | None = None) -> None:
    """Seed demo runs if they are not already present.

    Also re-seeds any existing demo run whose report is missing or
    unreadable (e.g. after a container restart that cleared the on-disk
    .md files before the markdown_text column was added).
    """
    # main.py's lifespan already installs the offline router unconditionally
    # before calling this, but this function is also exercised directly (by
    # tests) without that lifespan running first. Installing it here too is
    # idempotent and guarantees the demo runs' offline/ model calls resolve
    # regardless of caller.
    from co_scientist.offline_llm import install_offline_router

    install_offline_router()

    existing = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=db_path)
    existing_by_goal = _runs_by_goal(existing)

    for goal in _DEMO_GOALS:
        await _seed_or_reseed_demo_run(
            goal, existing_by_goal.get(goal), db_path
        )
