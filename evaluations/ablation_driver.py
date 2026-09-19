"""Controlled feature-ablation driver (L11): reachable strategy/tool arms.

Runs paired arms across a small set of goals through the real durable path,
each arm identical except for one capability toggle, and emits the
``ablations`` records ``evaluations.scaling_eval.ablation_summary`` already
reads.

**Reachable arms** -- config-level toggles the durable path honors. Most
resolve at the capability boundary (``opts_capabilities.py``); the
web-search disable instead rides ``opts.py::_resolve_disabled_tools`` into
the engine's ``disable_tools`` list (see ``AGENTS.md``'s "Per-run tool
disabling is reconciled once, at registry load"):

- ``baseline`` -- every toggle at its default.
- ``no_web_search`` -- ``enable_web_search=False``. Disables the engine's
  ``web_search`` tool specifically; ``read_url`` stays enabled since it also
  backs unrelated content retrieval.
- ``no_literature_review`` -- ``enable_literature_review=False``. Disables
  the whole literature-review node.
- ``no_meta_review`` -- ``enable_meta_review=False``. Gates the scheduler's
  periodic meta-review cadence check
  (``scheduling.policy_cadence._check_meta_review_cadence``, which covers
  both the ordered step and the companion path). This is "no *periodic*
  meta-review", NOT "no meta-review agent": the EVOLVE branch still enters
  the meta_review node (``generator/graph._TASK_ROUTES``, out of this
  driver's reach), so the node can still run to feed evolution. The off
  path degrades cleanly -- every consumer reads ``state["meta_review"]``,
  which stays the empty ``{}`` it starts at and renders nothing, exactly
  as cycle one already does.
- ``debate_only_strategy`` -- ``generation_strategy="no_lit"``. Forces the
  debate-only generation strategy instead of deriving the mix from
  literature/tool availability
  (``coordinator_strategy._forced_generation_strategy``). Offline this is
  identical to ``baseline`` by construction: with no literature the
  derivation already picks debate-only, so the override only bites on a
  live run that *had* literature -- and even then ``no_lit`` still reserves
  an assumptions slice, whose technique grounds against any literature the
  run holds, so a live ``no_lit`` arm is debate-without-literature for the
  bulk of the batch rather than a literature-free run end to end. (A
  "no-debate" tools-only arm is
  expressible via the same seam -- ``dev_isolation``/``lit_and_tools`` --
  but is live-only: the resolver refuses a tools-requiring strategy when
  tool-calling generation is off, and the offline backend emits no tool
  calls.)

**Honesty on effect:** these toggles are now *wired*, not *shown to
matter*. Offline every arm degrades to the same LLM-only, no-tools,
debate-only path (see below), so the offline sweep proves the switches
reach the engine and a run still completes -- it does not measure any
ablation effect. ``PUBLISHED_BASELINES`` below records Google's own
numbers for the meta-review and evolution arms (plus Reflection's
search-tool arm, reachable via ``no_web_search``), quoted from the paper
as reference data a future credentialed ``--live`` sweep can be read
against -- never computed, compared, or gated on here. The Evolution
arm remains *unreachable* (``_UNREACHABLE_ARMS``): no engine switch
disables the Evolution agent.

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
    # Export explicit MODEL_NAME and OPENROUTER_API_KEY before live use.
    python -m evaluations.ablation_driver --live
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
    # Periodic meta-review cadence off (the meta_review node can still run
    # via the EVOLVE branch); forced debate-only generation strategy. Both
    # are engine-side toggles added for this driver -- see the module
    # docstring's Reachable arms.
    "no_meta_review": {"enable_meta_review": False},
    "debate_only_strategy": {"generation_strategy": "no_lit"},
}

_UNREACHABLE_ARMS = {
    "no_evolution": (
        "No engine switch disables the Evolution agent; evolution is driven "
        "by the scheduler's generation-vs-evolution decision, not a config "
        "toggle. The only per-run evolution knob is the numeric "
        "evolution_max_count, and the app path can only raise it above its "
        "tier baseline (run_modes._apply_numeric_override is max()), never "
        "to zero. PUBLISHED_BASELINES['evolution'] records Google's numbers "
        "for this arm as reference data a future credentialed sweep could "
        "be read against."
    ),
}

# Google's own published per-agent ablation numbers (Nature SI Note 3 /
# Supplementary Table 1; docs/CORPUS-EXTRACTION.md R11-8). Landed here as a
# READ-ONLY comparison baseline for the day a credentialed --live sweep with
# real toggles exists -- see the two _UNREACHABLE_ARMS above, which are
# exactly the arms these numbers cover. Nothing in this module computes,
# compares, or gates against these; they are quoted reference data only. In
# each metric pair, "baseline" is the paper's full-system run and "ablated"
# is the same run with that agent/tool removed, in the order the source
# states them.
PUBLISHED_BASELINES: dict[str, dict[str, Any]] = {
    "reflection_search_tool": {
        "source": "Nature SI Note 3 / Supplementary Table 1 (corpus R11-8)",
        "arm_removed": "Reflection's search tool",
        "metrics": {
            "novelty": {"baseline": 6.14, "ablated": 2.38},
            "correctness": {"baseline": 7.4, "ablated": 8.46},
            "gpqa_auc": {"baseline": 0.643, "ablated": 0.651},
        },
        "note": (
            "Not uniformly directional: correctness IMPROVES when the "
            "search tool is ablated while novelty collapses. Both numbers "
            "are published as-is -- do not smooth this into one "
            "consistent story."
        ),
    },
    "evolution": {
        "source": "Nature SI Note 3 / Supplementary Table 1 (corpus R11-8)",
        "arm_removed": "the Evolution agent",
        "metrics": {
            "gpqa_precision_pct": {"baseline": 70.9, "ablated": 75.4},
            "quality": {"baseline": 4.7, "ablated": 5.6},
        },
    },
    "meta_review": {
        "source": "Nature SI Note 3 / Supplementary Table 1 (corpus R11-8)",
        "arm_removed": "the Meta-review agent",
        "metrics": {
            "auc_constructed": {"baseline": 0.521, "ablated": 0.597},
            "auc_gpqa": {"baseline": 0.629, "ablated": 0.634},
        },
    },
}

# Named by the same source but NOT quantified in the corpus extraction --
# docs/CORPUS-EXTRACTION.md R11-8 records only "plus Ranking-prompt and
# Proximity findings", with no numbers. Recorded so a reader knows these
# exist in Google's published ablation table and their absence here is a
# documented extraction gap, never a claim that no effect was found.
PUBLISHED_BASELINES_UNQUANTIFIED: dict[str, str] = {
    "ranking_prompt": (
        "Named in Nature SI Note 3 / Supplementary Table 1 but no numbers "
        "are captured in docs/CORPUS-EXTRACTION.md R11-8."
    ),
    "proximity": (
        "Named in Nature SI Note 3 / Supplementary Table 1 but no numbers "
        "are captured in docs/CORPUS-EXTRACTION.md R11-8."
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
        "evaluation_identity": arm.get("evaluation_identity"),
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
        "cost_basis": "partial_static_estimate",
        "usage_evidence": arm["metrics"].get("usage_evidence"),
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
        computed ablation summary, the documented unreachable arms, and
        Google's own published baselines for those unreachable arms
        (reference data only -- never compared against `summary` here).
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
        "published_baselines": PUBLISHED_BASELINES,
        "published_baselines_unquantified": PUBLISHED_BASELINES_UNQUANTIFIED,
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
        help="Run live with explicit verified free MODEL_NAME.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the CLI: drive the sweep, write the artifact, print a summary."""
    args = _parse_args()
    report = run_ablation_sweep(_DEFAULT_GOALS, args.tier, live=args.live)
    out = write_dated_artifact(report, "ablation-sweep")

    print(f"ablation sweep: mode={report['mode']} tier={report['tier']}")
    print(f"  paired_goal_count={report['summary']['paired_goal_count']}")
    for arm, stats in report["summary"]["arms"].items():
        print(f"  arm={arm} {stats}")
    print(f"  unreachable_arms={sorted(report['unreachable_arms'])}")
    print(f"  published_baselines={sorted(report['published_baselines'])}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
