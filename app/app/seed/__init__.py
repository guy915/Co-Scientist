from __future__ import annotations

import logging
from typing import Any

from app.demo_seed_data import DEMO_SCENARIOS, DEMO_SEED_VERSION
from app.run_modes import resolved_run_config, setup_config
from app.seed.scenario import (
    _scenario_planning_lists as _scenario_planning_lists,
)
from app.seed.scenario import (
    _seed_curated_scenario as _seed_curated_scenario,
)
from app.store import db, interviews, runs
from app.store import reports as store
from app.store import runs_views as views
from app.store.models import DEMO_CLIENT_ID, RunRow
from app.store.runs import RunCreateOptions

logger = logging.getLogger(__name__)

_DEMO_GOALS = list(DEMO_SCENARIOS)


def _build_demo_run_config(goal: str) -> dict[str, Any]:
    """Version the entire curated artifact bundle so older demos are
    replaced once per content revision.
    """
    scenario = DEMO_SCENARIOS[goal]
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
    if run is not None:
        return run
    scenario = DEMO_SCENARIOS[goal]
    return runs.create_run(
        goal,
        str(config["tier"]),
        "engine",
        config,
        RunCreateOptions(
            client_id=DEMO_CLIENT_ID,
            title=f"Example: {scenario.title}",
            llm_backend="offline",
            db_path=db_path,
        ),
    )


def _scenario_report_is_current(run: RunRow, db_path: str | None) -> bool:
    report = store.get_latest_report(run.id, db_path=db_path)
    setup = run.config.get("setup") if isinstance(run.config, dict) else None
    interview = interviews.get_interview(str(run.config.get("interview_id") or ""), db_path=db_path)
    return bool(
        interview
        and interview["client_id"] == DEMO_CLIENT_ID
        and report
        and report["payload"].get("demo_seed_version") == DEMO_SEED_VERSION
        and run.config.get("demo_seed_version") == DEMO_SEED_VERSION
        and isinstance(setup, dict)
        and setup.get("requirements")
        and setup.get("attributes")
        and run.config.get("interview_id")
        and run.config.get("example_chat_version") == DEMO_SEED_VERSION
    )


async def _seed_demo_run(
    goal: str,
    run: RunRow | None,
    db_path: str | None,
) -> None:
    config = _build_demo_run_config(goal)
    run = _ensure_demo_run_row(goal, run, config, db_path)
    scenario = DEMO_SCENARIOS[goal]
    # Reconstructed legacy demo rows need the same setup fields as newly
    # created ones.
    if run.config.get("interview_id"):
        config["interview_id"] = run.config["interview_id"]
    runs.set_run_config(run.id, config, db_path=db_path)
    run.profile = str(config["tier"])
    with db.connect(db_path) as conn:
        conn.execute("UPDATE runs SET profile=? WHERE id=?", (run.profile, run.id))
    await _seed_curated_scenario(run, scenario, db_path)
    logger.info("Seeded curated demo run %s (%.60s…)", run.id[:8], goal)


async def _seed_or_reseed_demo_run(
    goal: str,
    run: RunRow | None,
    db_path: str | None,
) -> None:
    """A failed demo seed must not abort app startup or prevent later
    examples from being tried.
    """
    if run is not None:
        if _scenario_report_is_current(run, db_path):
            logger.info("demo run %s already has a report, skipping", run.id[:8])
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
    # Direct callers bypass lifespan setup; idempotent offline-router
    # installation keeps demo calls deterministic there too.
    from co_scientist.offline.llm import install_offline_router

    install_offline_router()

    existing = views.list_runs(client_id=DEMO_CLIENT_ID, db_path=db_path)
    existing_by_goal = {run.research_goal: run for run in existing}

    for goal in _DEMO_GOALS:
        await _seed_or_reseed_demo_run(goal, existing_by_goal.get(goal), db_path)
