"""Controlled multi-budget scaling-curve driver (L9).

Runs the SAME research goal across the run tiers (express / standard /
extended / ultra, see ``app.run_modes.RUN_TIER_DEFAULTS``) through
the real durable path, differing only in tier -- no numeric overrides, since
a request-body override may only *raise* a tier baseline, never lower it,
and a raised knob would stop an arm from differing by budget alone. Emits
the ``snapshots`` shape ``evaluations.scaling_eval.scaling_curve`` already
reads, and calls that function so the artifact carries the computed curve
too, not just the raw per-arm snapshots. Each snapshot also carries
``temporal_curve`` (R1-13): Google's own published within-run method
(``scaling_eval.temporal_scaling_curve``) applied to that arm's own
hypotheses -- ten equal buckets ordered by authoring cycle
(``creation_iteration``, falling back to ``generation``), best/
top-10-average Elo per bucket. It never varies tier.

**Offline (default, the only mode CI or a committed test exercises):**
proves the driver's wiring end-to-end against the deterministic offline LLM
backend. It demonstrates that the harness runs and that the four tiers
really do request increasing hypothesis/tournament/evidence counts -- it is
NOT evidence that a real model's output quality scales with compute budget,
since the offline backend answers every call the same canned way regardless
of tier. Every offline artifact this driver writes carries an explicit
``offline_disclaimer`` field saying so. That disclaimer covers the
cross-tier ``curve`` only -- each arm's own ``temporal_curve`` orders by
a real signal even offline (``creation_iteration``, the engine's
authoring-cycle ordinal, falling back to ``generation`` when a legacy
hypothesis carries none), not by comparing identical canned answers
across tiers, though it is coarser than the paper's continuous wall-clock
partition: see ``scaling_eval.temporal_scaling_curve``'s docstring for the
resolution caveat, and note an express/standard arm only ever reaches
authoring cycle 0 and 1 (one evolution round).

**Live (``--live``, opt-in only, never run automatically):** needs a real
provider key (``OPENROUTER_API_KEY``) and, for literature grounding, a
reachable MCP server (``MCP_SERVER_URL``, default localhost:8888). A full
four-tier live sweep is real provider spend and real wall-clock time (the
``ultra`` tier alone runs 16 hypotheses and 32 tournament pairs); it is the
operator's explicit decision, made by passing ``--live``, never a default.

Run:
    python -m evaluations.scaling_budget_driver                  # offline
    python -m evaluations.scaling_budget_driver --tiers express,ultra
    # Export explicit MODEL_NAME and OPENROUTER_API_KEY before live use.
    python -m evaluations.scaling_budget_driver --live
"""

from __future__ import annotations

import argparse
import pathlib
import tempfile
from collections.abc import Sequence
from typing import Any

from evaluations import _run_driver
from evaluations._artifacts import write_dated_artifact
from evaluations.scaling_eval import scaling_curve, temporal_scaling_curve

# Mirrors app.run_modes.RUN_TIER_DEFAULTS's key order (smallest budget
# first); duplicated as a plain tuple so this module's CLI default does not
# need an app import before _run_driver has set up the app import path.
_ALL_TIERS = ("express", "standard", "extended", "ultra")

_DEFAULT_GOAL = (
    "Identify a novel small-molecule strategy to restore chemosensitivity "
    "in platinum-resistant high-grade serous ovarian cancer."
)
_GOAL_ID = "scaling-budget-curve-goal"

_OFFLINE_DISCLAIMER = (
    "This curve ran against the deterministic offline LLM backend "
    "(COSCIENTIST offline router). It demonstrates the driver's wiring "
    "end-to-end and that each tier really does request more compute "
    "(hypotheses/tournament pairs/evidence). It is NOT evidence that a "
    "real model's output quality scales with budget: the offline backend "
    "answers every call the same canned way regardless of tier, so "
    "'best_elo' and 'top10_diversity' differences here reflect pool size, "
    "not model behavior."
)


def _arm_to_snapshot(arm: dict[str, Any]) -> dict[str, Any]:
    """Shape one driven arm into the snapshot ``scaling_curve`` reads.

    Also carries ``temporal_curve`` (R1-13): Google's published within-run
    method, applied to this arm's own hypotheses. Unlike the cross-tier
    ``curve`` this driver already builds, this orders by a real per-arm
    signal (``creation_iteration``, falling back to ``generation``) rather
    than by tier -- see ``scaling_eval.temporal_scaling_curve`` for what
    that ordering can and cannot resolve.
    """
    return {
        "run_id": arm["run_id"],
        "goal": arm.get("goal"),
        "tier": arm.get("tier"),
        "overrides": arm.get("overrides"),
        "evaluation_identity": arm.get("evaluation_identity"),
        "goal_id": _GOAL_ID,
        "metrics": arm["metrics"],
        "hypotheses": arm["hypotheses"],
        "temporal_curve": temporal_scaling_curve(arm["hypotheses"]),
    }


def run_budget_curve(
    goal: str, tiers: Sequence[str], *, live: bool
) -> dict[str, Any]:
    """Drive one arm per tier and return the full curve report.

    Args:
        goal: The single research goal every tier arm shares.
        tiers: Ordered tier names to run (smallest budget first).
        live: When True, run on the real provider backend; the caller must
            already have confirmed a provider key is available.

    Returns:
        A JSON-safe report: the goal, mode, per-arm detail, snapshots, and
        the computed scaling curve.
    """
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="scaling-curve-"))
    _run_driver.configure_environment(
        str(tmp / "scaling.db"), str(tmp / "cache"), live=live
    )
    backend = "real" if live else "offline"
    arms = [
        _run_driver.run_arm(
            goal,
            tier,
            {},
            _run_driver.ArmInvocation(
                client_id=f"scaling-curve:{tier}",
                backend=backend,
                db_path=str(tmp / "scaling.db"),
            ),
        )
        for tier in tiers
    ]
    from evaluations._identity import validate_comparison

    validation = validate_comparison(arms, kind="scaling")
    snapshots = [_arm_to_snapshot(arm) for arm in arms]
    return {
        "comparison_validation": validation,
        "goal": goal,
        "goal_id": _GOAL_ID,
        "mode": "live" if live else "offline",
        "offline_disclaimer": None if live else _OFFLINE_DISCLAIMER,
        "tiers": list(tiers),
        "arms": arms,
        "snapshots": snapshots,
        "curve": scaling_curve(snapshots),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tiers",
        default=",".join(_ALL_TIERS),
        help="Comma-separated tiers, smallest budget first.",
    )
    parser.add_argument("--goal", default=_DEFAULT_GOAL)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run live with explicit verified free MODEL_NAME.",
    )
    return parser.parse_args()


def _print_temporal_curves(report: dict[str, Any]) -> None:
    """Print each arm's within-run temporal Elo curve (R1-13)."""
    for snapshot in report["snapshots"]:
        print(f"  temporal curve for {snapshot['run_id']}:")
        for bucket in snapshot["temporal_curve"]:
            print(
                f"      bucket {bucket['bucket']}/{bucket['of']} "
                f"n={bucket['n_hypotheses']:<2} "
                f"best_elo={bucket['best_elo']} "
                f"top10_avg_elo={bucket['top10_avg_elo']}"
            )


def main() -> int:
    """Run the CLI: drive the curve, write the artifact, print a summary."""
    args = _parse_args()
    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]
    report = run_budget_curve(args.goal, tiers, live=args.live)
    out = write_dated_artifact(report, "scaling-budget-curve")

    print(f"scaling budget curve: mode={report['mode']} tiers={tiers}")
    for point in report["curve"]:
        print(
            f"  llm_calls={point['compute']['llm_calls']:>5} "
            f"tasks={point['compute']['tasks']:>4} "
            f"best_elo={point['best_elo']} "
            f"top10_diversity={point['top10_diversity']} "
            f"verified_claim_ratio={point['verified_claim_ratio']} "
            f"cost_usd={point['cost_usd']} "
            f"latency_s={point['latency_seconds']}"
        )
    _print_temporal_curves(report)
    if report["offline_disclaimer"]:
        print(f"NOTE: {report['offline_disclaimer']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
