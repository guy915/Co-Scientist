"""Shared setup for the phase-3 DBOS experiments (branch proto/dbos only).

Import this before any `app` module: it pins the database path, forces the
offline backend and enables the DBOS review route.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))


def configure(db_path: str, *, dbos: bool = True) -> None:
    os.environ["COSCIENTIST_DB_PATH"] = db_path
    os.environ["COSCIENTIST_FORCE_OFFLINE"] = "1"
    os.environ["FORCE_LITERATURE_REVIEW"] = "0"
    os.environ["COSCIENTIST_DBOS_REVIEW"] = "1" if dbos else "0"
    for key in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        os.environ.pop(key, None)


def task_state(run_id: str, count: int) -> dict[str, Any]:
    from co_scientist.models import ExecutionMetrics, Hypothesis

    return {
        "run_id": run_id,
        "research_goal": "DBOS prototype",
        "model_name": "fixture",
        "supervisor_model_name": "fixture",
        "hypotheses": [Hypothesis(text=f"h{index:03d}") for index in range(count)],
        "articles": [],
        "messages": [],
        "metrics": ExecutionMetrics(),
        "mcp_available": False,
        "current_iteration": 0,
        "start_time": time.time(),
    }


def seed_review(count: int, *, zero_cost: bool = False, config: dict[str, Any] | None = None) -> tuple[str, str, int]:
    """A run whose next claimable task is the review node."""
    from co_scientist.checkpoint import CHECKPOINT_VERSION, serialize_workflow_state

    from app.store import checkpoints, runs, tasks
    from app.store.checkpoints import NewCheckpoint
    from app.store.runs import RunCreateOptions
    from app.store.tasks import NewTask

    run_config = dict(config or {})
    if zero_cost:
        run_config["zero_cost_admission"] = True
    run = runs.create_run(
        "DBOS prototype",
        "standard",
        "engine",
        run_config,
        RunCreateOptions(client_id="proto", llm_backend="offline"),
    )
    envelope = serialize_workflow_state(task_state(run.id, count), last_event_seq=0)
    seq = checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
            stage="fixture",
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=0,
            state={"provider": "engine", "resume_successor": "engine.node.review", **envelope},
        ),
    )
    task = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.node.review",
            inputs={"checkpoint_seq": seq},
            idempotency_key=f"proto:review:{seq}",
            priority=90,
        )
    )
    return run.id, task.id, seq


def install_fake_review(call_log: str, delay: float) -> None:
    """Every provider call appends a `start` line before it waits, so the
    log counts issued calls even when the process dies mid-call.
    """
    import asyncio

    import co_scientist.agents.reflection.review as review_module
    from co_scientist.llm import ModelCallStats, record_call
    from co_scientist.models import HypothesisReview

    async def fake_review(*, hypothesis_text: str, **_: Any) -> HypothesisReview:
        _log(call_log, {"event": "start", "hypothesis": hypothesis_text})
        record_call("fixture-model", ModelCallStats(calls=1, prompt_tokens=20, completion_tokens=10))
        await asyncio.sleep(delay)
        _log(call_log, {"event": "end", "hypothesis": hypothesis_text})
        return HypothesisReview(
            review_summary=f"reviewed {hypothesis_text}",
            scores={"scientific_soundness": 8, "novelty": 8},
            safety_ethical_concerns="none",
            detailed_feedback={},
            constructive_feedback="continue",
            overall_score=8.0,
        )

    review_module.review_single_hypothesis = fake_review  # type: ignore[assignment]


def _log(path: str, record: dict[str, Any]) -> None:
    record = {**record, "pid": os.getpid(), "t": time.time()}
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_log(path: str) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def calls_per_hypothesis(path: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in read_log(path):
        if record["event"] == "start":
            counts[record["hypothesis"]] = counts.get(record["hypothesis"], 0) + 1
    return counts


def latest_checkpoint_summary(run_id: str) -> dict[str, Any]:
    from app.store import checkpoints

    checkpoint = checkpoints.get_latest_checkpoint(run_id)
    assert checkpoint is not None
    hypotheses = checkpoint["state"]["state"]["hypotheses"]
    return {
        "seq": checkpoint["seq"],
        "stage": checkpoint["stage"],
        "reviewed": sum(1 for h in hypotheses if h.get("reviews")),
        "review_failed": sum(1 for h in hypotheses if h.get("review_disposition") == "review_failed"),
        "reviews_total": sum(len(h.get("reviews") or []) for h in hypotheses),
        "hypotheses": len(hypotheses),
    }
