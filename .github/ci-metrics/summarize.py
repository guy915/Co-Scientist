"""Render a timing snapshot collected with GitHub's workflow-runs/jobs APIs."""

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median


def seconds(end: str, start: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def show(values: list[float]) -> str:
    return f"{median(values):g}" if values else "—"


def summarize(runs: list[dict]) -> str:
    lines = [
        "All times are seconds. Job wall = completed − created; queue = started − created;",
        "execution = completed − started. Workflow wall = updated − created (API terminal",
        "timestamp). Initial dispatch = first job created − workflow created, separate",
        "from runner queue. Job medians include success/failure; skipped/cancelled jobs",
        "are counted separately and excluded from timing medians. Workflow medians",
        "include every sampled terminal run, including cancelled runs. Matrices skipped",
        "before expansion appear under their literal expression names. Samples are the",
        "latest 20 completed CI main-push runs and latest 20 completed CI PR runs at",
        "collection time; attempts use the latest available jobs. No success-only filter.",
        "",
    ]
    for event, label in [("push", "main"), ("pull_request", "PR")]:
        selected = [run for run in runs if run["event"] == event]
        if not selected:
            continue
        lines += [f"## {label} ({len(selected)} runs)", ""]
        walls = [seconds(run["updated_at"], run["created_at"]) for run in selected]
        dispatch = [
            seconds(min(job["created_at"] for job in run["jobs"]), run["created_at"])
            for run in selected
        ]
        lines += [
            f"Workflow wall median **{show(walls)} s**; max **{max(walls):g} s**.",
            f"Initial dispatch median **{show(dispatch)} s**; max **{max(dispatch):g} s**.",
            "",
            "| Job | Timed n | Skipped | Cancelled | Wall median | Queue median | Queue max | Execution median |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        jobs = defaultdict(list)
        for run in selected:
            for job in run["jobs"]:
                jobs[job["name"]].append(job)
        for name, samples in sorted(jobs.items()):
            active = [
                job
                for job in samples
                if job["conclusion"] not in {"skipped", "cancelled"}
                and job["started_at"]
                and job["completed_at"]
            ]
            queue = [seconds(job["started_at"], job["created_at"]) for job in active]
            wall = [seconds(job["completed_at"], job["created_at"]) for job in active]
            execution = [
                seconds(job["completed_at"], job["started_at"]) for job in active
            ]
            skipped = sum(job["conclusion"] == "skipped" for job in samples)
            cancelled = sum(job["conclusion"] == "cancelled" for job in samples)
            maximum = f"{max(queue):g}" if queue else "—"
            lines.append(
                f"| {name} | {len(active)} | {skipped} | {cancelled} | {show(wall)} | "
                f"{show(queue)} | {maximum} | {show(execution)} |"
            )
        lines += ["", "### Sample provenance", ""]
        for run in selected:
            lines.append(
                f"- [Run {run['id']}]({run['html_url']}): {run['created_at']}, "
                f"{run['conclusion']}, attempt {run['run_attempt']}, `{run['head_sha'][:12]}`"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


if __name__ == "__main__":
    print(summarize(json.loads(Path(sys.argv[1]).read_text())))
