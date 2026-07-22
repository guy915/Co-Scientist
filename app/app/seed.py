"""Startup seeding for demo runs.

Creates three completed demo runs that newcomers can browse. Demo runs use
client_id=DEMO_CLIENT_ID and are seeded once; subsequent restarts are no-ops
if all three already exist. Runs through the real engine pinned to the
offline deterministic backend (no LLM provider required, no API spend).
"""

from __future__ import annotations

import logging
from typing import Any

from app import engine_adapter, store
from app.run_modes import resolved_run_config, setup_config
from app.store import DEMO_CLIENT_ID, RunRow

logger = logging.getLogger(__name__)

# Demo runs are seeded at the smallest tier: they drive the full real engine
# graph (offline-backed) inside the startup lifespan, so keeping the compute
# envelope small keeps startup responsive while still producing a complete,
# presentable report per goal.
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

# Curated session titles for the demo runs, so they showcase the distinct-
# heading behavior without a model call at seed time (seeding runs the real
# engine pinned to the deterministic offline backend).
_DEMO_TITLES: dict[str, str] = {
    _DEMO_GOALS[0]: "Antibiotic Resistance in S. aureus Biofilms",
    _DEMO_GOALS[1]: "Synaptic Pruning and Cognitive Flexibility",
    _DEMO_GOALS[2]: "Ferroptosis Regulators in Pancreatic Cancer",
}


def _build_demo_run_config(goal: str) -> dict[str, Any]:
    """Build the resolved run config for one demo goal.

    Express tier keeps the startup cost of driving the full engine graph
    bounded (a standard-tier offline run costs tens of seconds per goal);
    literature review is off because seeding runs MCP-less by design, so
    probing for a server would only add latency, never evidence.
    """
    return resolved_run_config(
        {
            "setup": setup_config(research_goal=goal, tier=_DEMO_TIER),
            "enable_literature_review": False,
            "llm_backend": "offline",
        }
    )


def _ensure_demo_run_row(
    goal: str,
    run: RunRow | None,
    config: dict[str, Any],
    db_path: str | None,
) -> RunRow:
    """Return `run`, creating the demo run row first if one doesn't exist."""
    if run is not None:
        return run
    return store.create_run(
        research_goal=goal,
        profile=_DEMO_TIER,
        provider="engine",
        config=config,
        client_id=DEMO_CLIENT_ID,
        title=_DEMO_TITLES.get(goal),
        llm_backend="offline",
        db_path=db_path,
    )


async def _seed_demo_run(
    goal: str,
    run: RunRow | None,
    db_path: str | None,
) -> None:
    """Create (if needed) and drive the offline-backed engine for one demo goal.

    Args:
        goal: The demo research goal to seed.
        run: The existing run row for this goal, or None to create one.
        db_path: Optional override for the SQLite database path.
    """
    config = _build_demo_run_config(goal)
    run = _ensure_demo_run_row(goal, run, config, db_path)
    # force_provider="engine" runs demo seeding through the real engine
    # graph; the "llm_backend": "offline" override above pins it to the
    # deterministic offline router regardless of whether a real LLM key is
    # configured, so startup never spends API budget and demo content stays
    # reproducible while still exercising the actual agent pipeline.
    # sleep_seconds=0.0 skips the boundary emitter's pacing so seeding
    # finishes immediately rather than over several seconds.
    async for _ in engine_adapter.run_workflow(
        run_id=run.id,
        research_goal=goal,
        config=config,
        db_path=db_path,
        sleep_seconds=0.0,
        force_provider="engine",
    ):
        pass  # events are persisted as a side effect; drain and drop.
    logger.info("Seeded demo run %s (%.60s…)", run.id[:8], goal)


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
    """Seed `goal`, skipping any existing run that already has a report.

    A failed seed must not take down app startup; it is logged and swallowed
    here so the caller can move on to the next demo goal.
    """
    if run is not None:
        if _has_readable_report(run, db_path):
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
