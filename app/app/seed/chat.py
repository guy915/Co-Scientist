"""Curated example conversations are fixtures, never model-generated runs."""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.demo_seed_data import DEMO_SEED_VERSION, DemoScenario
from app.store import db, runs
from app.store.models import RunRow


def seed_example_chat(
    run: RunRow, scenario: DemoScenario, db_path: str | None
) -> None:
    current = runs.get_run(run.id, db_path=db_path)
    assert current is not None
    at = current.created_at
    setup = current.config["setup"]
    fields = {
        "research_challenge": run.research_goal,
        "title": f"Example: {scenario.title}",
        "focus_area": [a["name"] for a in setup["attributes"]],
        "preferences": setup["requirements"],
        "lab_constraints": [],
    }
    turns = [
        ("user", run.research_goal),
        (
            "agent",
            "This is a curated example conversation and research plan. "
            "Its proposals illustrate the workflow, not validated findings. "
            "What should the comparison prioritize?",
        ),
        (
            "user",
            scenario.direction
            + "\n\nRequirements:\n"
            + "\n".join(setup["requirements"]),
        ),
        (
            "agent",
            "The example plan compares mechanisms using the stated "
            "requirements, attributes and criteria. " + scenario.direction,
        ),
    ]
    with db.transaction(db_path) as conn:
        previous = current.config.get("interview_id")
        interview_id = str(previous or uuid.uuid4())
        if previous:
            conn.execute(
                "DELETE FROM interviews WHERE id=? AND client_id=?",
                (interview_id, run.client_id),
            )
        conn.execute(
            "INSERT INTO interviews (id,client_id,status,fields_json,"
            "created_at,updated_at,completed_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                interview_id,
                run.client_id,
                "completed",
                json.dumps(fields),
                at,
                at + 40,
                at + 40,
            ),
        )
        for n, (role, content) in enumerate(turns):
            conn.execute(
                "INSERT INTO interview_turns "
                "(interview_id,role,content,created_at) VALUES (?,?,?,?)",
                (interview_id, role, content, at + n * 10),
            )
        config: dict[str, Any] = {
            **current.config,
            "example_chat_version": DEMO_SEED_VERSION,
            "interview_id": interview_id,
        }
        conn.execute(
            "UPDATE runs SET config_json=? WHERE id=?",
            (json.dumps(config), run.id),
        )
        conn.execute("DELETE FROM messages WHERE run_id=?", (run.id,))
        for sender, kind, content, timestamp in (
            ("user", "start", "Start research with this plan.", at + 41),
            (
                "system",
                "start",
                "This curated example includes its completed run. "
                "Ask about the ideas, reviews and evidence.",
                at + 42,
            ),
            (
                "user",
                "qa",
                "What do these proposals suggest, and what remains uncertain?",
                (current.completed_at or at + 50) - 2,
            ),
            (
                "system",
                "qa",
                scenario.summary + "\n\n" + scenario.meta_review,
                (current.completed_at or at + 50) - 1,
            ),
        ):
            conn.execute(
                "INSERT INTO messages (run_id,sender,kind,content,created_at) "
                "VALUES (?,?,?,?,?)",
                (run.id, sender, kind, content, timestamp),
            )
