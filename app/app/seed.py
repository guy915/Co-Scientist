# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Startup seeding for demo runs.

Creates three completed demo runs that newcomers can browse. Demo runs use
client_id=DEMO_CLIENT_ID and are seeded once; subsequent restarts are no-ops
if all three already exist. Uses the mock workflow (no LLM provider required).
"""

from __future__ import annotations

import logging

from app import store
from app.mock_workflow import run_mock_workflow

logger = logging.getLogger(__name__)

DEMO_CLIENT_ID = "__demo__"

_DEMO_GOALS: list[tuple[str, str]] = [
    (
        "What mechanisms drive antibiotic resistance in Staphylococcus aureus biofilms, "  # pylint: disable=line-too-long
        "and which metabolic pathways could be targeted to restore susceptibility?",  # pylint: disable=line-too-long
        "standard",
    ),
    (
        "How does synaptic pruning in the prefrontal cortex contribute to cognitive "  # pylint: disable=line-too-long
        "flexibility during adolescent development?",
        "standard",
    ),
    (
        "What are the key molecular regulators of ferroptosis in pancreatic cancer cells, "  # pylint: disable=line-too-long
        "and how might their modulation enhance chemotherapy sensitivity?",
        "standard",
    ),
]


async def seed_demo_runs(db_path: str | None = None) -> None:
    """Seed demo runs if they are not already present."""
    existing = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=db_path)
    if len(existing) >= len(_DEMO_GOALS):
        logger.info("demo runs already seeded (%d found), skipping",
                    len(existing))
        return

    existing_goals = {r.research_goal for r in existing}
    for goal, profile in _DEMO_GOALS:
        if goal in existing_goals:
            continue
        try:
            run = store.create_run(
                research_goal=goal,
                profile=profile,
                provider="mock",
                config={},
                client_id=DEMO_CLIENT_ID,
                db_path=db_path,
            )
            async for _ in run_mock_workflow(
                    run_id=run.id,
                    research_goal=goal,
                    profile=profile,
                    config={},
                    db_path=db_path,
                    sleep_seconds=0.0,
            ):
                pass
            logger.info("Seeded demo run %s (%.60s…)", run.id[:8], goal)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Failed to seed demo run for goal: %.60s", goal)
