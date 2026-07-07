"""Startup seeding for demo runs.

Creates three completed demo runs that newcomers can browse. Demo runs use
client_id=DEMO_CLIENT_ID and are seeded once; subsequent restarts are no-ops
if all three already exist. Uses the mock workflow (no LLM provider required).
"""

from __future__ import annotations

import logging

from app import engine_adapter, store
from app.run_modes import CANONICAL_RUN_MODE
from app.store import DEMO_CLIENT_ID

logger = logging.getLogger(__name__)

_DEMO_GOALS: list[tuple[str, str]] = [
    (
        "What mechanisms drive antibiotic resistance in Staphylococcus aureus biofilms, "  # pylint: disable=line-too-long
        "and which metabolic pathways could be targeted to restore susceptibility?",  # pylint: disable=line-too-long
        CANONICAL_RUN_MODE,
    ),
    (
        "How does synaptic pruning in the prefrontal cortex contribute to cognitive "  # pylint: disable=line-too-long
        "flexibility during adolescent development?",
        CANONICAL_RUN_MODE,
    ),
    (
        "What are the key molecular regulators of ferroptosis in pancreatic cancer cells, "  # pylint: disable=line-too-long
        "and how might their modulation enhance chemotherapy sensitivity?",
        CANONICAL_RUN_MODE,
    ),
]


async def seed_demo_runs(db_path: str | None = None) -> None:
    """Seed demo runs if they are not already present.

    Also re-seeds any existing demo run whose report is missing or
    unreadable (e.g. after a container restart that cleared the on-disk
    .md files before the markdown_text column was added).
    """
    existing = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=db_path)
    existing_by_goal = {r.research_goal: r for r in existing}

    for goal, run_mode in _DEMO_GOALS:
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
            if run is None:
                run = store.create_run(
                    research_goal=goal,
                    profile=run_mode,
                    provider="mock",
                    config={},
                    client_id=DEMO_CLIENT_ID,
                    db_path=db_path,
                )
            async for _ in engine_adapter.run_workflow(
                    run_id=run.id,
                    research_goal=goal,
                    config={},
                    db_path=db_path,
                    sleep_seconds=0.0,
                    force_provider="mock",
            ):
                pass
            logger.info("Seeded demo run %s (%.60s…)", run.id[:8], goal)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Failed to seed demo run for goal: %.60s", goal)
