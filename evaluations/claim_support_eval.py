"""How much of what a run asserts is backed by something it retrieved.

The unsupported-claim rate is the blunt end of the deep-research work: if
going back for what a first search left open is worth its cost, this is
the number it has to move. It is deliberately computed from verdicts the
run already recorded rather than re-judged here -- ``claim_evidence``
rows are written by the production assessor (``app.claims.verifier``), and
a second, lexical opinion invented inside an eval is how a metric comes
to disagree with the product it is measuring. That failure has a name in
this repo: the Jaccard incident, where a short claim scored against a
long abstract made the two upper verdict states unreachable and every
citation in every run classified ``unsupported``.

"Supported" therefore means exactly what the report means by it -- a
``supports`` or ``partial`` claim-evidence edge -- reused from
``_run_driver`` rather than restated.

Two rates, because they answer different questions:

- **unsupported_claim_rate** -- over every assessed claim. The direct
  measure, and the one a retrieval change should move.
- **unverified_idea_rate** -- over hypotheses. An idea whose every claim
  went unsupported is what a reader actually sees badged "Unverified", so
  a change that helps already-well-supported ideas and no others shows up
  here as no movement.

**Offline by default, and that proves wiring, not quality.** The
deterministic offline backend answers every assessment the same canned
way whatever was retrieved, so an offline number says the path computes;
it says nothing about whether research improved support. Offline
artifacts carry an ``offline_disclaimer`` saying so. ``--run <id>``
scores a real persisted run, which is the mode that means something.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT / "app") not in sys.path:
    sys.path.insert(0, str(_ROOT / "app"))

from evaluations._artifacts import write_dated_artifact  # noqa: E402
from evaluations._run_driver import (  # noqa: E402
    ArmInvocation,
    configure_environment,
    hypotheses_with_claim_counts,
    run_arm,
)

_OFFLINE_DISCLAIMER = (
    "Offline run: the deterministic backend answers every claim assessment "
    "identically regardless of what was retrieved, so this rate proves the "
    "measurement path and not that research improved support."
)

_GOAL = (
    "Propose a mechanism for acquired resistance to EGFR tyrosine kinase "
    "inhibitors in EGFR-mutant lung adenocarcinoma."
)


def score_claims(annotated: list[dict[str, Any]]) -> dict[str, Any]:
    """No assessed claims means an unknown rate, not perfect support."""
    assessed = sum(int(h.get("assessed_claims") or 0) for h in annotated)
    supported = sum(int(h.get("verified_claims") or 0) for h in annotated)
    with_claims = [h for h in annotated if int(h.get("assessed_claims") or 0)]
    unverified = [h for h in with_claims if not int(h.get("verified_claims") or 0)]
    return {
        "ideas": len(annotated),
        "ideas_with_assessed_claims": len(with_claims),
        "claims_assessed": assessed,
        "claims_supported": supported,
        "unsupported_claim_rate": _rate(assessed - supported, assessed),
        "unverified_idea_rate": _rate(len(unverified), len(with_claims)),
    }


def _rate(part: int, total: int) -> float | None:
    return round(part / total, 4) if total else None


def score_run(run_id: str, db_path: str | None = None) -> dict[str, Any]:
    from app.store import hypotheses as store
    from app.store import records, runs
    from app.store import retrieval_calls as retrieval

    from evaluations._usage_evidence import summarize_usage

    metrics = retrieval.get_run_metrics(run_id, db_path=db_path) or {}
    run = runs.get_run(run_id, db_path=db_path)
    hyps = store.list_hypotheses(run_id, db_path=db_path)
    edges = records.list_claim_evidence(run_id, db_path=db_path)
    return {
        "run_id": run_id,
        "configured_backend": run.llm_backend if run is not None else None,
        "evaluation_identity": (run.config.get("evaluation_identity") if run is not None else None),
        "usage_evidence": summarize_usage(metrics.get("model_usage") or {}),
        **score_claims(hypotheses_with_claim_counts(hyps, edges)),
    }


def drive_and_score(
    goal: str = _GOAL, tier: str = "express", *, live: bool = False
) -> dict[str, Any]:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(pathlib.Path(tmp) / "claims.db")
        cache_dir = str(pathlib.Path(tmp) / "cache")
        configure_environment(db_path, cache_dir, live=live)
        arm = run_arm(
            goal,
            tier,
            {},
            ArmInvocation(
                client_id="claim-support-eval",
                backend="real" if live else "offline",
                db_path=db_path,
            ),
        )
    return {
        "run_id": arm["run_id"],
        "tier": tier,
        "completed": arm["completed"],
        "used_real_backend": arm["used_real_backend"],
        "evaluation_identity": arm.get("evaluation_identity"),
        "llm_calls": arm["metrics"]["llm_calls"],
        "latency_seconds": arm["metrics"]["latency_seconds"],
        "usage_evidence": arm["metrics"]["usage_evidence"],
        **score_claims(arm["hypotheses"]),
    }


def run(run_id: str | None, *, live: bool = False, tier: str = "express") -> dict[str, Any]:
    if run_id:
        return {
            "mode": "persisted_run",
            "offline_disclaimer": None,
            **score_run(run_id),
        }
    return {
        "mode": "live" if live else "offline",
        "offline_disclaimer": None if live else _OFFLINE_DISCLAIMER,
        "goal": _GOAL,
        **drive_and_score(tier=tier, live=live),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default=None, help="Score this run instead.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Drive the run against a real provider (needs a key).",
    )
    parser.add_argument(
        "--tier",
        default="express",
        choices=("express", "standard", "extended", "ultra"),
        help="Run size for a driven run.",
    )
    args = parser.parse_args()

    report = run(args.run, live=args.live, tier=args.tier)
    out = write_dated_artifact(report, f"claim-support-{report['mode']}")
    print(
        f"claim support [{report['mode']}]: "
        f"claims={report['claims_assessed']} "
        f"unsupported_claim_rate={report['unsupported_claim_rate']} "
        f"unverified_idea_rate={report['unverified_idea_rate']}"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
