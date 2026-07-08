"""Startup seeding for demo runs.

Creates three completed demo runs that newcomers can browse. Demo runs use
client_id=DEMO_CLIENT_ID and are seeded once; subsequent restarts are no-ops
if all three already exist. Uses the mock workflow (no LLM provider required).
"""

from __future__ import annotations

import logging

from app import engine_adapter, store
from app.run_modes import (
    CANONICAL_RUN_MODE,
    resolved_run_config,
    setup_config,
)
from app.store import DEMO_CLIENT_ID, RunRow

logger = logging.getLogger(__name__)

_DEMO_GOALS: list[str] = [
    "What mechanisms drive antibiotic resistance in Staphylococcus aureus "
    "biofilms, and which metabolic pathways could be targeted to restore "
    "susceptibility?",
    "How does synaptic pruning in the prefrontal cortex contribute to "
    "cognitive flexibility during adolescent development?",
    "What are the key molecular regulators of ferroptosis in pancreatic cancer "
    "cells, and how might their modulation enhance chemotherapy sensitivity?",
]


async def _seed_demo_run(
    goal: str,
    run: RunRow | None,
    db_path: str | None,
) -> None:
    """Create (if needed) and drive the mock workflow for one demo goal.

    Args:
        goal: The demo research goal to seed.
        run: The existing run row for this goal, or None to create one.
        db_path: Optional override for the SQLite database path.
    """
    config = resolved_run_config({"setup": setup_config(research_goal=goal)})
    if run is None:
        run = store.create_run(
            research_goal=goal,
            profile=CANONICAL_RUN_MODE,
            provider="mock",
            config=config,
            client_id=DEMO_CLIENT_ID,
            db_path=db_path,
        )
    # force_provider="mock" pins demo seeding to the deterministic
    # workflow even when a real LLM key is configured, so startup
    # never spends API budget and demo content is reproducible.
    # sleep_seconds=0.0 skips the mock's synthetic event pacing so
    # seeding finishes immediately rather than over several seconds.
    async for _ in engine_adapter.run_workflow(
            run_id=run.id,
            research_goal=goal,
            config=config,
            db_path=db_path,
            sleep_seconds=0.0,
            force_provider="mock",
    ):
        pass  # events are persisted as a side effect; drain and drop.
    logger.info("Seeded demo run %s (%.60s…)", run.id[:8], goal)


async def seed_demo_runs(db_path: str | None = None) -> None:
    """Seed demo runs if they are not already present.

    Also re-seeds any existing demo run whose report is missing or
    unreadable (e.g. after a container restart that cleared the on-disk
    .md files before the markdown_text column was added).
    """
    existing = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=db_path)
    existing_by_goal = {r.research_goal: r for r in existing}

    for goal in _DEMO_GOALS:
        run = existing_by_goal.get(goal)
        if run is not None:
            # Check whether the report is readable; skip if it is.
            md = store.read_report_markdown(run.id, db_path=db_path)
            if md is not None:
                logger.info(
                    "demo run %s already has a report, skipping",
                    run.id[:8],
                )
                continue
            logger.info(
                "demo run %s exists but has no readable report; re-seeding",
                run.id[:8],
            )
        try:
            await _seed_demo_run(goal, run, db_path)
        except Exception:  # pylint: disable=broad-exception-caught
            # A failed seed must not take down app startup; log and move on
            # to the next demo goal.
            logger.exception("Failed to seed demo run for goal: %.60s", goal)
