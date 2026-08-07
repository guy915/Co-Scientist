"""Controlled feature-ablation driver (L11): reachable strategy/tool arms.

Runs paired arms across a small set of goals through the real durable path,
each arm identical except for one capability toggle, and emits the
``ablations`` records ``evaluations.scaling_eval.ablation_summary`` already
reads.

**Reachable arms** -- config-level toggles the durable path honors (see
``app/app/engine_adapter/opts.py::_resolve_generator_disable_tools`` and
``_resolve_literature_review_toggle``, and ``AGENTS.md``'s "Per-run tool
disabling is reconciled once, at registry load"):

- ``baseline`` -- every toggle at its default.
- ``no_web_search`` -- ``enable_web_search=False``. Disables the engine's
  ``web_search`` tool specifically; ``read_url`` stays enabled since it also
  backs unrelated content retrieval.
- ``no_literature_review`` -- ``enable_literature_review=False``. Disables
  the whole literature-review node. This is also the closest reachable proxy
  for a *generation-strategy* ablation: per
  ``agents/generation/coordinator.py``, generation runs 100% debate-only
  when there is no literature review, versus a 50/50 tool-based /
  debate-with-literature split when there is.

**Not built here, and why:** an arm that disables meta-review, or one that
disables the debate strategy independently of literature-review
availability. Neither has an engine-level switch to flip --
``GeneratorOptions`` (``engine/src/co_scientist/generator/options.py``)
carries no such field, meta-review runs unconditionally every cycle, and the
debate/tool-based generation mix is *derived* from literature/tool
availability rather than toggled directly. Building either would mean
adding a new switch to the engine, which is out of this driver's ownership
-- see the evaluation report for what that would need.

**Offline (default):** proves the driver's wiring end-to-end. It is NOT
evidence that any toggle changes real output: without a reachable MCP
server, every arm's literature review already degrades to LLM-only, so
``no_web_search`` and ``no_literature_review`` are expected to look near-
identical to ``baseline`` offline. That is a statement about this sandbox's
plumbing, not a finding about the product.

**Live (``--live``, opt-in only):** needs a real provider key and a
reachable MCP server to make the toggles actually bite.

Run:
    python -m evaluations.ablation_driver                 # offline
    DEEPSEEK_API_KEY=... python -m evaluations.ablation_driver --live
"""

from __future__ import annotations

import argparse
import pathlib
import tempfile
from typing import Any

from evaluations import _run_driver
from evaluations._artifacts import write_dated_artifact
from evaluations.metrics import hypothesis_diversity
from evaluations.scaling_eval import ablation_summary

_ARMS: dict[str, dict[str, Any]] = {
    "baseline": {},
    "no_web_search": {"enable_web_search": False},
    "no_literature_review": {"enable_literature_review": False},
}

_UNREACHABLE_ARMS = {
    "no_meta_review": (
        "No engine switch exists to skip meta-review; it runs "
        "unconditionally every cycle (agents/meta_review/meta_review.py)."
    ),
    "no_debate_strategy": (
        "The debate/tool-based generation mix is derived from literature/"
        "tool availability (agents/generation/coordinator.py), not exposed "
        "as an independent toggle; GeneratorOptions carries no such field."
    ),
}

_DEFAULT_GOALS = (
    (
        "ablation-goal-1",
        "Propose a mechanism by which senescent stromal cells promote "
        "pancreatic ductal adenocarcinoma chemoresistance.",
    ),
    (
        "ablation-goal-2",
        "Identify a combination strategy to overcome acquired resistance "
        "to BTK inhibitors in chronic lymphocytic leukemia.",
    ),
)
_DEFAULT_TIER = "express"


def _arm_record(
    arm: dict[str, Any], goal_id: str, arm_name: str
) -> dict[str, Any]:
    """Shape one driven arm into the record ``ablation_summary`` reads."""
    hyps = arm["hypotheses"]
    texts = [h["text"] for h in hyps]
    total_assessed = sum(h["assessed_claims"] for h in hyps)
    total_verified = sum(h["verified_claims"] for h in hyps)
    return {
        "goal_id": goal_id,
        "arm": arm_name,
        "run_id": arm["run_id"],
        "completed": arm["completed"],
        # No expert panel; ablation_summary treats a missing quality score
        # as an omission, never as a zero.
        "expert_quality": None,
        "diversity": hypothesis_diversity(texts),
        "verified_claim_ratio": (
            round(total_verified / total_assessed, 4)
            if total_assessed
            else None
        ),
        "cost_usd": arm["metrics"]["cost_usd"],
        "latency_seconds": arm["metrics"]["latency_seconds"],
    }


def _drive_every_pair(
    goals: tuple[tuple[str, str], ...],
    tier: str,
    arm_overrides: dict[str, dict[str, Any]],
    db_path: str,
    *,
    live: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run every (goal, arm) pair and return (driven detail, records).

    Args:
        goals: ``(goal_id, goal_text)`` pairs every arm shares.
        tier: The shared run tier every arm executes at.
        arm_overrides: Arm name to generator-option overrides.
        db_path: Store the sweep's runs land in.
        live: When True, run on the real provider backend.

    Returns:
        The per-pair run detail and the summarizable records.
    """
    backend = "real" if live else "offline"
    driven: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for goal_id, goal_text in goals:
        for arm_name, overrides in arm_overrides.items():
            arm = _run_driver.run_arm(
                goal_text,
                tier,
                overrides,
                _run_driver.ArmInvocation(
                    client_id=f"ablation:{arm_name}:{goal_id}",
                    backend=backend,
                    db_path=db_path,
                ),
            )
            driven.append({**arm, "goal_id": goal_id, "arm": arm_name})
            records.append(_arm_record(arm, goal_id, arm_name))
    return driven, records


def run_ablation_sweep(
    goals: tuple[tuple[str, str], ...],
    tier: str,
    *,
    live: bool,
    arms: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Drive every (goal, arm) pair and return the full ablation report.

    Args:
        goals: ``(goal_id, goal_text)`` pairs every arm shares.
        tier: The shared run tier every arm executes at.
        live: When True, run on the real provider backend; the caller must
            already have confirmed a provider key is available.
        arms: Override the arm set (mainly for a smaller test sweep);
            defaults to the module's reachable arms.

    Returns:
        A JSON-safe report: per-arm run detail, the paired records, the
        computed ablation summary, and the documented unreachable arms.
    """
    arm_overrides = _ARMS if arms is None else arms
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ablation-sweep-"))
    db_path = str(tmp / "ablation.db")
    _run_driver.configure_environment(db_path, str(tmp / "cache"), live=live)
    driven, records = _drive_every_pair(
        goals, tier, arm_overrides, db_path, live=live
    )
    return {
        "tier": tier,
        "mode": "live" if live else "offline",
        "goals": dict(goals),
        "arms_run": sorted(arm_overrides),
        "unreachable_arms": _UNREACHABLE_ARMS,
        "driven": driven,
        # "ablations" is the key evaluations.scaling_eval.main() reads
        # (payload.get("ablations", [])); "records" is kept as a readable
        # alias for the same list so a human skimming the artifact isn't
        # stuck guessing what "ablations" means.
        "records": records,
        "ablations": records,
        "summary": ablation_summary(records),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", default=_DEFAULT_TIER)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run on the real provider backend (costs money and time).",
    )
    return parser.parse_args()


def main() -> int:
    """Run the CLI: drive the sweep, write the artifact, print a summary."""
    args = _parse_args()
    if args.live and not _run_driver.load_provider_key():
        raise SystemExit("no DEEPSEEK_API_KEY available; cannot run --live")
    report = run_ablation_sweep(_DEFAULT_GOALS, args.tier, live=args.live)
    out = write_dated_artifact(report, "ablation-sweep")

    print(f"ablation sweep: mode={report['mode']} tier={report['tier']}")
    print(f"  paired_goal_count={report['summary']['paired_goal_count']}")
    for arm, stats in report["summary"]["arms"].items():
        print(f"  arm={arm} {stats}")
    print(f"  unreachable_arms={sorted(report['unreachable_arms'])}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
