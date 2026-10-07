"""Check 2: leases, retry budgets, future-due tasks and steering admission
behave as docs/OPERATIONS.md requires, on the DBOS review port.

One process, DBOS launched off-loop; each scenario seeds its own run, drives
the review node through the real worker (`task_worker.run_once`) and scripts
the fake provider per call (harness.FAKE_SCRIPT).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from typing import Any

import harness

WORKDIR = tempfile.mkdtemp(prefix="dbos-c2-")
harness.configure(f"{WORKDIR}/co.db")
os.environ["WORKER_POOL_SIZE"] = "4"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

from dbos import DBOS  # noqa: E402

from app import dbos_proto, task_worker  # noqa: E402
from app.store import messages, runs, tasks  # noqa: E402
from app.store import tasks_lifecycle as lifecycle  # noqa: E402

CONFIG = {"max_iterations": 1, "max_llm_calls": 400}


def _calls(log: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for record in harness.read_log(log):
        out.setdefault(record["hypothesis"], []).append(record)
    return out


def _summary(run_id: str, seq: int) -> dict[str, Any]:
    from app.store import checkpoints

    latest = checkpoints.get_latest_checkpoint(run_id)
    assert latest is not None
    hyps = latest["state"]["state"]["hypotheses"]
    return {
        "committed": latest["seq"] > seq,
        "reviewed": sorted(h["text"] for h in hyps if h.get("reviews")),
        "review_failed": sorted(h["text"] for h in hyps if h.get("review_disposition") == "review_failed"),
        "run_status": runs.get_run(run_id).status,  # type: ignore[union-attr]
        "queued_successors": [t.task_type for t in tasks.list_tasks(run_id) if t.status == "queued"],
        "pending_steering": len(messages.get_pending_steering(run_id)),
    }


async def _start(run_id: str) -> str:
    assert await task_worker.run_once("proto", run_id=run_id)
    node = [t for t in tasks.list_tasks(run_id) if t.task_type == "engine.node.review"][0]
    return str(node.result["dbos_workflow_id"])  # type: ignore[index]


async def _result(workflow_id: str) -> Any:
    # Sync API on a worker thread: an async DBOS API would install DBOS's
    # executor as this loop's default, and asyncio.run would shut it down.
    return await asyncio.to_thread(lambda: DBOS.retrieve_workflow(workflow_id).get_result())


def scenario(name: str, script: dict[str, list[str]], *, items: int = 4, delay: float = 0.2,
             during: Any = None, zero_cost: bool = False) -> dict[str, Any]:
    log = f"{WORKDIR}/{name}.jsonl"
    os.environ["FAKE_SCRIPT"] = json.dumps(script)
    harness.install_fake_review(log, delay)
    run_id, _, seq = harness.seed_review(items, config=CONFIG, zero_cost=zero_cost)

    async def drive() -> tuple[Any, Any]:
        workflow_id = await _start(run_id)
        observed = await during(run_id, workflow_id, log) if during else None
        try:
            result = await asyncio.wait_for(_result(workflow_id), 120)
        except Exception as exc:  # Reported, not raised: the scenario records it.
            result = {"raised": repr(exc)[:200]}
        return result, observed

    started = time.time()
    result, observed = asyncio.run(drive())
    calls = _calls(log)
    return {
        "scenario": name,
        "script": script,
        "workflow_result": result,
        "observed_during": observed,
        "calls_per_hypothesis": {h: sum(1 for r in rs if r["event"] == "start") for h, rs in sorted(calls.items())},
        "call_start_times": {h: [round(r["t"] - started, 2) for r in rs if r["event"] == "start"] for h, rs in sorted(calls.items())},
        "cancelled_calls": {h: sum(1 for r in rs if r["event"] == "cancelled") for h, rs in calls.items() if any(r["event"] == "cancelled" for r in rs)},
        **_summary(run_id, seq),
    }


async def _probe_park(run_id: str, workflow_id: str, log: str) -> dict[str, Any]:
    # Wait until the parked call returned, then sample cohort liveness while
    # the durable sleep is pending.
    for _ in range(200):
        if any(r["event"] == "end" and r["hypothesis"] == "h000" for r in harness.read_log(log)):
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.5)
    claimable, active, parked_until = lifecycle.cohort_poll(run_id)
    return {
        "cohort_poll_during_park": {"claimable": claimable, "active": active, "parked_until": parked_until},
        "startup_lists_run": run_id in tasks.list_active_engine_task_run_ids(),
    }


def _cancel_probe(hook: bool):  # type: ignore[no-untyped-def]
    async def probe(run_id: str, workflow_id: str, log: str) -> dict[str, Any]:
        from app.runs.lifecycle import cancel_run

        for _ in range(200):
            if sum(1 for r in harness.read_log(log) if r["event"] == "start") >= 4:
                break
            await asyncio.sleep(0.05)
        cancelled_at = time.time()
        await cancel_run(run_id)  # off_loop wraps it as a coroutine
        if hook:
            await asyncio.to_thread(DBOS.cancel_workflow, workflow_id)
            from procs import query

            rows = query(f"{WORKDIR}/co.db", "SELECT workflow_uuid FROM workflow_status WHERE substr(workflow_uuid,1,?)=?", (len(workflow_id) + 1, workflow_id + ":"))
            children = [r["workflow_uuid"] for r in rows]
            for child in children:
                await asyncio.to_thread(DBOS.cancel_workflow, child)
        await asyncio.sleep(8)
        after = [r for r in harness.read_log(log) if r["t"] > cancelled_at]
        return {
            "dbos_cancel_hook": hook,
            "calls_started_after_cancel": sum(1 for r in after if r["event"] == "start"),
            "calls_finished_after_cancel": sum(1 for r in after if r["event"] == "end"),
            "calls_cancelled_after_cancel": sum(1 for r in after if r["event"] == "cancelled"),
            "first_end_after_cancel_s": round(min((r["t"] for r in after if r["event"] == "end"), default=cancelled_at) - cancelled_at, 2),
        }

    return probe


async def _steer(run_id: str, workflow_id: str, log: str) -> dict[str, Any]:
    from app.store.messages import NewMessage

    await asyncio.sleep(0.3)
    message = messages.append_message(NewMessage(run_id, "scientist", "focus on mechanism", "steering"))
    return {"steering_message_id": message.id}


def main() -> int:
    dbos_proto.launch()
    from co_scientist.llm import provider_outage_backoff_seconds

    only = set(sys.argv[1:])
    results = [] if only else [
        scenario("retry_budget", {"h000": ["value_error"] * 3, "h001": ["value_error", "value_error", "ok"]}),
        scenario("call_budget_exceeded", {"h000": ["budget"]}, delay=0.5),
        scenario("rate_park", {"h000": ["park:2", "value_error", "value_error", "value_error"]}, during=_probe_park),
        scenario("unknown_provider_outcome", {"h000": ["timeout_unknown"]}),
        scenario("zero_cost_timeout", {"h000": ["timeout_free", "ok"]}, zero_cost=True),
    ]
    results.append(scenario("cancel_run_with_port_hook", {}, items=8, delay=3.0, during=_cancel_probe(False)))
    results += [] if only else [
        scenario("steering_during_review", {}, delay=1.0, during=_steer),
    ]
    results.append({"reference": {"provider_outage_backoff_seconds(1)": provider_outage_backoff_seconds(1)}})
    print(json.dumps(results, indent=2, default=str))
    dbos_proto.shutdown()
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
