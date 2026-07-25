"""Report and compare run latency cohorts from the durable task spine.

The benchmark every latency change is measured against. It profiles a set of
runs (see ``stage_latency_analysis`` for how time is attributed), prints the
stage breakdown, and can save a cohort to JSON so a later cohort can be
diffed against it.

Usage::

    # Baseline the last 7 standard runs and save them.
    python -m dev.stage_latency --tier standard --limit 7 \\
        --save .remember/tmp/baseline.json --label baseline

    # After a change, compare a fresh cohort against that baseline.
    python -m dev.stage_latency --tier standard --limit 7 \\
        --since 2026-07-24 --compare-to .remember/tmp/baseline.json

Run it from ``app/``. ``--db`` defaults to the same database the app uses.

Baseline, seven most recent completed runs as of 2026-07-24 (commit
5218432f)::

    wall   mean 33.9m   p50 27.8m   p95 76.3m   range 14.4m-76.3m
    active 33.9m        idle 0.1s   worker-time sum 53.9m
    target mean <= 27.1m

    engine.node.ranking                 21.7%   n 3.6   p50  1.6m
    engine.fanout.generation.strategy   13.8%   n 6.6   p50  2.2m
    engine.ranking.match                13.3%   n 22.3  p50 19.3s
    engine.fanout.reflection.item        8.7%   n 22.7  p50 20.9s
    engine.fanout.verification.item      8.3%   n 5.9   p50 43.5s
    engine.node.research_overview        5.8%   n 1.0   p50  2.1m
    engine.node.orchestrator             5.6%   n 4.7   p50 22.9s
    engine.node.literature_review        5.3%   n 1.0   p50  1.7m

Two properties of that baseline shape the work queued behind it. Idle time
is ~0, so there is no queue latency to reclaim -- every second is inside a
task. And ``solo_s`` equals ``wall_share_s`` for every stage, meaning no two
stage kinds ever overlap: the run executes as a strictly serial spine.

That second property is an observation about how the pipeline is *wired*,
not a law about how it must be. Several stages read only a hypothesis's
text and write disjoint fields, so they are chained without a data
dependency forcing it. Whether unchaining them would actually pay is what
the occupancy report answers:

    python -m dev.stage_latency --tier standard --limit 7 --cohort-size 8

``free`` is the mean worker slots a stage left unused. A stage with several
free slots can host an independent stage alongside it for nothing -- the
cohort was going to idle anyway. A stage reported as ``saturated`` cannot:
overlapping it only requeues the same work behind the same eight workers,
and its latency has to come from a wider cohort or a shorter chain. Read
this table before proposing either fix; the two readings prescribe opposite
work and the wall-share table alone cannot tell them apart.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Sequence
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dev.stage_latency_analysis import (  # noqa: E402
    DEFAULT_COHORT_SIZE,
    RunProfile,
    StageStats,
    load_spans,
    percentile,
    profile_run,
    run_tier,
)


def _configured_cohort_size() -> int:
    """Return the app's worker_pool_size, or the module default.

    Read from the live setting rather than assumed, so the occupancy report
    compares against the ceiling the runs were actually executed under. A
    report that measured 8 concurrent tasks against a wrongly assumed
    ceiling of 12 would read as comfortable headroom when the cohort was in
    fact saturated -- the exact conclusion this report exists to get right.
    """
    try:
        from app.config import settings

        return int(settings.worker_pool_size)
    except Exception:
        return DEFAULT_COHORT_SIZE

# The plan's first-wave goal: a cohort must come in at or below this
# fraction of the baseline mean to count as a win.
FIRST_WAVE_TARGET_FRACTION = 0.80

_DEFAULT_DB = os.environ.get("COSCIENTIST_DB_PATH", "coscientist.db")

# Terminal statuses worth benchmarking. A cancelled or failed run stopped
# early, so its wall time measures the failure, not the pipeline.
_MEASURED_RUN_STATUS = ("completed",)


def _git_commit() -> str:
    """Return the current HEAD short sha, or 'unknown' outside a checkout."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out.stdout.strip() or "unknown"


def _parse_date(value: str) -> float:
    """Parse a YYYY-MM-DD date into epoch seconds."""
    return time.mktime(time.strptime(value, "%Y-%m-%d"))


def _select_runs(
    conn: sqlite3.Connection, args: argparse.Namespace
) -> list[sqlite3.Row]:
    """Return the run rows matching the CLI's cohort filters."""
    clauses = ["status IN ({})".format(
        ",".join("?" for _ in _MEASURED_RUN_STATUS)
    )]
    params: list[Any] = list(_MEASURED_RUN_STATUS)
    if args.run:
        clauses.append("id = ?")
        params.append(args.run)
    if args.since:
        clauses.append("created_at >= ?")
        params.append(_parse_date(args.since))
    if args.until:
        clauses.append("created_at < ?")
        params.append(_parse_date(args.until))
    sql = (
        "SELECT id, profile, status, config_json, created_at FROM runs "
        f"WHERE {' AND '.join(clauses)} ORDER BY created_at DESC"
    )
    return list(conn.execute(sql, params).fetchall())


def _profiles_for(
    conn: sqlite3.Connection, args: argparse.Namespace
) -> list[RunProfile]:
    """Build the cohort's run profiles, applying tier and limit filters."""
    rows = _select_runs(conn, args)
    spans = load_spans(conn, [row["id"] for row in rows])
    profiles: list[RunProfile] = []
    for row in rows:
        tier = run_tier(row["config_json"], row["profile"])
        if args.tier and tier != args.tier:
            continue
        profile = profile_run(
            row["id"],
            tier,
            row["status"],
            spans.get(row["id"], []),
            cohort_size=args.cohort_size,
        )
        if profile is not None:
            profiles.append(profile)
        if args.limit and len(profiles) >= args.limit:
            break
    return profiles


def _merge_stages(profiles: Sequence[RunProfile]) -> list[StageStats]:
    """Aggregate per-run stage stats into one cohort-wide table.

    Percentiles are recomputed over the pooled per-invocation durations
    rather than averaged across runs, since averaging percentiles of
    different sample sizes is not a percentile of anything.
    """
    totals: dict[str, dict[str, float]] = {}
    for profile in profiles:
        for stage in profile.stages:
            entry = totals.setdefault(
                stage.task_type,
                {"invocations": 0.0, "wall": 0.0, "solo": 0.0, "worker": 0.0},
            )
            entry["invocations"] += stage.invocations
            entry["wall"] += stage.wall_share_s
            entry["solo"] += stage.solo_s
            entry["worker"] += stage.worker_s

    runs = max(1, len(profiles))
    merged = [
        StageStats(
            task_type=task_type,
            invocations=round(entry["invocations"] / runs, 2),
            wall_share_s=entry["wall"] / runs,
            solo_s=entry["solo"] / runs,
            worker_s=entry["worker"] / runs,
            p50_s=_pooled(profiles, task_type, 0.5),
            p95_s=_pooled(profiles, task_type, 0.95),
        )
        for task_type, entry in totals.items()
    ]
    return sorted(merged, key=lambda s: -s.wall_share_s)


def _pooled(
    profiles: Sequence[RunProfile], task_type: str, fraction: float
) -> float:
    """Return a percentile over every run's per-invocation p50 for a stage."""
    samples = [
        stage.p50_s
        for profile in profiles
        for stage in profile.stages
        if stage.task_type == task_type
    ]
    return percentile(samples, fraction)


def _cohort(
    profiles: Sequence[RunProfile], label: str, db_path: str
) -> dict[str, Any]:
    """Build the serializable cohort summary."""
    walls = [profile.wall_s for profile in profiles]
    mean = sum(walls) / len(walls) if walls else 0.0
    return {
        "label": label,
        "commit": _git_commit(),
        "db_path": db_path,
        "generated_at": time.time(),
        "run_count": len(profiles),
        "mean_wall_s": mean,
        "p50_wall_s": percentile(walls, 0.5),
        "p95_wall_s": percentile(walls, 0.95),
        "min_wall_s": min(walls) if walls else 0.0,
        "max_wall_s": max(walls) if walls else 0.0,
        "target_mean_s": mean * FIRST_WAVE_TARGET_FRACTION,
        "mean_active_s": _mean(p.active_s for p in profiles),
        "mean_idle_s": _mean(p.idle_s for p in profiles),
        "mean_worker_s": _mean(
            sum(s.worker_s for s in p.stages) for p in profiles
        ),
        "stages": [stage.to_dict() for stage in _merge_stages(profiles)],
        "occupancy": _merge_occupancy(profiles),
        "runs": [profile.to_dict() for profile in profiles],
    }


def _merge_occupancy(profiles: Sequence[RunProfile]) -> dict[str, Any]:
    """Aggregate per-run occupancy into one cohort-wide summary.

    Per-stage figures are averaged over the runs that actually ran that
    stage, not over the whole cohort: a stage absent from a run contributes
    no occupancy observation, and counting it as zero would report an
    always-saturated stage as having headroom.
    """
    if not profiles:
        return {}
    by_stage: dict[str, list[Any]] = {}
    for profile in profiles:
        for stage in profile.occupancy.stages:
            by_stage.setdefault(stage.task_type, []).append(stage)
    stages = [
        {
            "task_type": task_type,
            "mean_concurrency": _mean(s.mean_concurrency for s in observed),
            "peak_concurrency": max(s.peak_concurrency for s in observed),
            "saturated_s": _mean(s.saturated_s for s in observed),
            "headroom": _mean(s.headroom for s in observed),
        }
        for task_type, observed in by_stage.items()
    ]
    return {
        "cohort_size": profiles[0].occupancy.cohort_size,
        "mean_concurrency": _mean(
            p.occupancy.mean_concurrency for p in profiles
        ),
        "peak_concurrency": max(
            p.occupancy.peak_concurrency for p in profiles
        ),
        "mean_saturated_s": _mean(p.occupancy.saturated_s for p in profiles),
        "stages": sorted(stages, key=lambda s: -float(s["headroom"])),
    }


def _mean(values: Any) -> float:
    """Return the arithmetic mean of an iterable, or 0.0 when empty."""
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def _fmt(seconds: float) -> str:
    """Render seconds as a compact minutes-and-seconds string."""
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.1f}s"


def _print_header(cohort: dict[str, Any]) -> None:
    """Print the cohort's run-level summary."""
    print(f"cohort: {cohort['label']}  commit={cohort['commit']}")
    print(f"runs:   {cohort['run_count']}")
    if not cohort["run_count"]:
        return
    print(
        f"wall:   mean {_fmt(cohort['mean_wall_s'])}  "
        f"p50 {_fmt(cohort['p50_wall_s'])}  "
        f"p95 {_fmt(cohort['p95_wall_s'])}  "
        f"range {_fmt(cohort['min_wall_s'])}-{_fmt(cohort['max_wall_s'])}"
    )
    print(
        f"busy:   active {_fmt(cohort['mean_active_s'])}  "
        f"idle {_fmt(cohort['mean_idle_s'])}  "
        f"(worker-time sum {_fmt(cohort['mean_worker_s'])}, "
        "double-counts concurrency)"
    )
    print(
        f"target: mean <= {_fmt(cohort['target_mean_s'])} "
        f"({int((1 - FIRST_WAVE_TARGET_FRACTION) * 100)}% reduction)"
    )


def _print_stages(cohort: dict[str, Any]) -> None:
    """Print the per-stage critical-path table."""
    active = cohort["mean_active_s"] or 1.0
    print()
    print(
        f"{'stage':<42}{'n':>6}{'wall':>9}{'%':>7}"
        f"{'solo':>9}{'p50':>8}{'p95':>8}"
    )
    for stage in cohort["stages"]:
        share = 100.0 * stage["wall_share_s"] / active
        print(
            f"{stage['task_type']:<42}"
            f"{stage['invocations']:>6}"
            f"{_fmt(stage['wall_share_s']):>9}"
            f"{share:>6.1f}%"
            f"{_fmt(stage['solo_s']):>9}"
            f"{_fmt(stage['p50_s']):>8}"
            f"{_fmt(stage['p95_s']):>8}"
        )


def _print_occupancy(cohort: dict[str, Any]) -> None:
    """Print worker-cohort utilization, most idle slots first.

    ``conc`` is every task in flight while the stage ran, not just its own,
    since that is what decides whether an independent stage could have run
    alongside it. A stage with wide headroom is a candidate for overlapping
    with one it does not depend on; a stage that is mostly saturated is not,
    and needs a wider cohort or a shorter chain instead.
    """
    occ = cohort.get("occupancy")
    if not occ:
        return
    size = occ["cohort_size"]
    print()
    print(
        f"worker occupancy (cohort {size}):  "
        f"mean {occ['mean_concurrency']:.1f} in flight  "
        f"peak {occ['peak_concurrency']}  "
        f"saturated {_fmt(occ['mean_saturated_s'])}/run"
    )
    print(
        f"{'stage':<42}{'conc':>7}{'peak':>6}{'free':>7}{'saturated':>11}"
    )
    for stage in occ["stages"]:
        print(
            f"{stage['task_type']:<42}"
            f"{stage['mean_concurrency']:>7.1f}"
            f"{stage['peak_concurrency']:>6}"
            f"{stage['headroom']:>7.1f}"
            f"{_fmt(stage['saturated_s']):>11}"
        )


def _print_widths(profiles: Sequence[RunProfile]) -> None:
    """Print mean fan-out width per wave across the cohort."""
    widths: dict[str, list[float]] = {}
    for profile in profiles:
        for family, width in profile.items_per_invocation.items():
            widths.setdefault(family, []).append(width)
    if not widths:
        return
    print()
    print("items per invocation (fan-out width):")
    for family, values in sorted(widths.items()):
        print(f"  {family:<44}{_mean(values):>6.1f}")


def _print_comparison(current: dict[str, Any], baseline_path: str) -> None:
    """Print the current cohort's deltas against a saved baseline."""
    with open(baseline_path, encoding="utf-8") as handle:
        baseline = json.load(handle)
    print()
    print(
        f"vs baseline '{baseline['label']}' "
        f"(commit={baseline['commit']}, n={baseline['run_count']}):"
    )
    base_mean = baseline["mean_wall_s"] or 1.0
    delta = current["mean_wall_s"] - baseline["mean_wall_s"]
    pct = 100.0 * delta / base_mean
    verdict = "MEETS" if pct <= -100 * (
        1 - FIRST_WAVE_TARGET_FRACTION
    ) else "below"
    print(
        f"  mean wall {_fmt(baseline['mean_wall_s'])} -> "
        f"{_fmt(current['mean_wall_s'])}  ({pct:+.1f}%)  [{verdict} target]"
    )
    _print_stage_deltas(current, baseline)


def _print_stage_deltas(
    current: dict[str, Any], baseline: dict[str, Any]
) -> None:
    """Print per-stage wall-share deltas, largest regression first."""
    base = {s["task_type"]: s["wall_share_s"] for s in baseline["stages"]}
    rows = [
        (s["task_type"], s["wall_share_s"] - base.get(s["task_type"], 0.0))
        for s in current["stages"]
    ]
    rows.sort(key=lambda row: row[1])
    for task_type, delta in rows:
        if abs(delta) < 1.0:
            continue
        print(f"  {task_type:<44}{_fmt(delta):>9} {'faster' if delta < 0 else 'slower'}")


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Critical-path latency report over durable run tasks."
    )
    parser.add_argument("--db", default=_DEFAULT_DB, help="SQLite path.")
    parser.add_argument("--run", help="Profile a single run id.")
    parser.add_argument("--tier", help="Filter to one run tier.")
    parser.add_argument("--since", help="Only runs created on/after YYYY-MM-DD.")
    parser.add_argument("--until", help="Only runs created before YYYY-MM-DD.")
    parser.add_argument("--limit", type=int, default=0, help="Max runs.")
    parser.add_argument("--label", default="current", help="Cohort name.")
    parser.add_argument("--save", help="Write the cohort JSON here.")
    parser.add_argument("--compare-to", help="Baseline cohort JSON to diff.")
    parser.add_argument("--json", action="store_true", help="Emit JSON only.")
    parser.add_argument(
        "--cohort-size",
        type=int,
        default=_configured_cohort_size(),
        help="Worker slots per run the occupancy report measures against.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the latency report."""
    args = _build_parser().parse_args(argv)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        profiles = _profiles_for(conn, args)
    finally:
        conn.close()

    cohort = _cohort(profiles, args.label, args.db)
    if args.json:
        print(json.dumps(cohort, indent=2))
    else:
        _print_header(cohort)
        if profiles:
            _print_stages(cohort)
            _print_occupancy(cohort)
            _print_widths(profiles)
        if args.compare_to:
            _print_comparison(cohort, args.compare_to)
    if args.save:
        with open(args.save, "w", encoding="utf-8") as handle:
            json.dump(cohort, handle, indent=2)
    return 0 if profiles else 1


if __name__ == "__main__":
    raise SystemExit(main())
