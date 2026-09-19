"""Shared durable-run driving plumbing for the controlled-experiment drivers.

L9 (budget scaling, ``scaling_budget_driver.py``) and L11 (feature ablation,
``ablation_driver.py``) both need to persist a research goal through the real
durable path -- ``store.create_run`` -> ``task_worker`` -> ``engine_tasks`` ->
engine -> drain -> report -- drain it to a terminal state, and read back the
artifacts a snapshot/record is built from. This module owns that shared
plumbing so the two drivers differ only in which config overrides they set
and how they shape the result.

The pattern (env-before-app-import, temp DB, ``resolved_run_config`` ->
``create_run`` -> ``enqueue_run_workflow`` -> ``run_run_worker_pool`` -> read
from store) is copied from ``golden_run.py``'s precedent, which drives one
live INDRA acceptance check rather than a controlled multi-arm sweep.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import pathlib
import sys
import time
from collections import defaultdict
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
# The viewer backend is a plain package under app/, imported the same way
# the offline evals and golden_run reach it; the engine is a real installed
# dependency and needs no path help.
if str(_ROOT / "app") not in sys.path:
    sys.path.insert(0, str(_ROOT / "app"))

_SUPPORTED_CLAIM_LABELS = ("supports", "partial")


def configure_environment(db_path: str, cache_dir: str, *, live: bool) -> None:
    """Set process env for one controlled-experiment invocation.

    Must run before any ``app``/``co_scientist`` import loads settings. A
    disabled response cache prevents a later arm from reusing an earlier
    arm's calls. The directory remains isolated for other cache artifacts.
    run_arm also scopes caching off to cover an already-created singleton.

    An offline invocation forces ``COSCIENTIST_FORCE_OFFLINE=1`` rather than
    merely omitting the provider key. The per-run ``llm_backend="offline"``
    passed to ``store.create_run`` only pins *that run's generator model* --
    a real key present in the process environment still leaves
    ``app.engine_adapter.offline_mode()`` (the process-level predicate
    ``app/app/safety.py``'s semantic escalation and other call sites read)
    reporting "real", which sent a genuine provider call from a run this
    driver believed was fully offline. Forcing it removes that ambiguity.

    Args:
        db_path: SQLite path for this invocation's runs.
        cache_dir: Directory for this invocation's LLM response cache.
        live: Whether this invocation may reach a real provider.
    """
    os.environ["COSCIENTIST_DB_PATH"] = db_path
    os.environ["COSCIENTIST_CACHE_DIR"] = cache_dir
    os.environ["COSCIENTIST_CACHE_ENABLED"] = "0"
    if not live:
        os.environ["COSCIENTIST_FORCE_OFFLINE"] = "1"
        # Forcing the flag is necessary but was not sufficient: it only
        # reaches call sites that consult it, and a credential left in the
        # environment is what any that do not will spend. Removing the
        # credentials makes "offline" unspendable rather than merely
        # intended. Matched by suffix instead of by a list, because the
        # equivalent hand-kept list in app/tests/conftest.py had already
        # fallen behind the app's own map once.
        for name in [n for n in os.environ if n.endswith("_API_KEY")]:
            del os.environ[name]
        # Offline literature review returns generated passages, which the
        # deterministic claim assessor cannot support a claim against, so
        # every idea is withheld and the run ends blocked before reaching
        # the report -- the stages an offline sweep exists to exercise. The
        # app suite disables the node for the same reason.
        os.environ["FORCE_LITERATURE_REVIEW"] = "0"
        return
    os.environ.pop("COSCIENTIST_FORCE_OFFLINE", None)
    os.environ.pop("COSCIENTIST_FORCE_MOCK", None)
    from evaluations._live_config import configure_live_environment

    configure_live_environment()


@dataclasses.dataclass(frozen=True)
class ArmInvocation:
    """The per-invocation identity/backend fields every arm run shares.

    Bundled so ``persist_arm_run``/``run_arm`` stay within the repo's
    5-parameter ceiling instead of threading ``client_id``/``backend``/
    ``db_path`` through separately.

    Attributes:
        client_id: Owning client id for each arm's persisted run row.
        backend: ``"offline"`` or ``"real"``.
        db_path: SQLite path shared across the invocation's arms.
    """

    client_id: str
    backend: str
    db_path: str


def persist_arm_run(
    goal: str, tier: str, overrides: dict[str, Any], invocation: ArmInvocation
) -> str:
    """Persist one arm's run row exactly as ``POST /api/runs`` would.

    Args:
        goal: The research goal text.
        tier: The run tier (``express``/``standard``/``extended``/``ultra``).
        overrides: Extra ``resolved_run_config`` overrides beyond the tier
            (e.g. a connector toggle). Empty for a pure budget arm.
        invocation: This arm's shared identity/backend/db fields.

    Returns:
        The new run's id.
    """
    from app import store
    from app.run_modes import resolved_run_config, setup_config

    config = resolved_run_config(
        {
            "setup": setup_config(research_goal=goal, tier=tier),
            "tier": tier,
            **overrides,
        }
    )
    from evaluations._comparison_identity import arm_identity

    config["evaluation_identity"] = arm_identity(
        goal, config, invocation.backend
    )
    run = store.create_run(
        goal,
        tier,
        "engine",
        config,
        store.RunCreateOptions(
            client_id=invocation.client_id,
            llm_backend=invocation.backend,
            db_path=invocation.db_path,
        ),
    )
    return str(run.id)


def drive_arm_run(run_id: str, db_path: str) -> tuple[int, float]:
    """Drain one run's durable task chain; return (event count, seconds).

    Mirrors the two steps ``POST /{id}/start`` performs. The cohort returns
    once no ready task and no live lease remain, so no polling is needed.
    Wall-clock time is measured here rather than read from the engine's own
    ``ExecutionMetrics.total_time``, which is only ever set on the removed
    in-process streaming path and stays 0.0 on the durable path these
    drivers use.
    """
    from app import store, task_worker
    from co_scientist.offline_llm import install_offline_router

    from evaluations._comparison_identity import validate_stored_arm

    identity = validate_stored_arm(run_id, db_path)

    # This driver calls ``run_run_worker_pool`` directly rather than going
    # through the app's lifespan or the standalone ``run_forever`` loop, and
    # neither installs the offline router for it. Idempotent and a harmless
    # passthrough for real models (see ``task_worker.run_forever``'s own
    # comment) -- install unconditionally rather than gate it on this
    # arm's backend.
    install_offline_router()
    task_worker.enqueue_run_workflow(
        run_id, force_provider="engine", db_path=db_path
    )
    start = time.monotonic()
    asyncio.run(
        task_worker.run_run_worker_pool(
            run_id,
            f"eval-driver:{run_id[:8]}",
            policy=task_worker.WorkerPolicy(db_path=db_path),
        )
    )
    elapsed = time.monotonic() - start
    validate_stored_arm(run_id, db_path, identity)
    return len(store.list_events(run_id, db_path=db_path)), elapsed


def _claim_counts_by_hypothesis(
    claim_edges: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, int]]:
    """Return (assessed, verified) claim counts keyed by hypothesis id.

    Mirrors ``app.report_content_gates``'s one definition of "verified" (a
    ``supports`` or ``partial`` claim-evidence edge) at per-hypothesis
    granularity -- the report's tile and badge share that rule, and these
    drivers must not invent a second one.
    """
    assessed: dict[str, int] = defaultdict(int)
    verified: dict[str, int] = defaultdict(int)
    for edge in claim_edges:
        hid = str(edge.get("hypothesis_id") or "")
        assessed[hid] += 1
        if edge.get("label") in _SUPPORTED_CLAIM_LABELS:
            verified[hid] += 1
    return dict(assessed), dict(verified)


def hypotheses_with_claim_counts(
    hyps: list[dict[str, Any]], claim_edges: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return each hypothesis with its claim assessed/verified counts.

    Carries ``creation_iteration``, ``generation`` and ``created_at``
    through unchanged (all present on every row ``store.list_hypotheses``
    returns) so ``scaling_eval.temporal_scaling_curve`` can bucket a run's
    hypotheses by authoring cycle -- the store itself returns hypotheses
    Elo-descending, not chronologically. ``creation_iteration`` is the
    timeline axis; ``generation`` is its fallback for a legacy row and
    ``created_at`` a final tie-break (see that function's docstring for why
    neither alone suffices).
    """
    assessed, verified = _claim_counts_by_hypothesis(claim_edges)
    out = []
    for h in hyps:
        hid = str(h.get("id") or "")
        out.append(
            {
                "id": hid,
                "text": str(h.get("text") or ""),
                "elo_rating": h.get("elo_rating"),
                "creation_iteration": h.get("creation_iteration"),
                "generation": h.get("generation"),
                "created_at": h.get("created_at"),
                "assessed_claims": assessed.get(hid, 0),
                "verified_claims": verified.get(hid, 0),
            }
        )
    return out


def run_completion_status(run: Any) -> tuple[bool, bool]:
    """Return (completed, ran_on_real_backend) for a persisted run row.

    The durable cohort returns when the queue drains, which a *failed* run
    also does; and a keyless environment answers every LLM call from the
    deterministic offline backend. Both must be checked explicitly rather
    than inferred from "the cohort returned".
    """
    from app import store

    if run is None:
        return False, False
    completed = run.status == store.RunStatus.COMPLETED.value
    return completed, not store.run_used_offline(run)


def compute_arm_metrics(
    run_id: str, db_path: str, wall_clock_seconds: float, tasks_count: int
) -> dict[str, Any]:
    """Return the ``{llm_calls, tasks, cost_usd, latency_seconds}`` metrics.

    ``cost_usd`` sums every ``model_usage`` entry's estimated cost; it is
    exactly 0.0 for an offline-backed run (offline/-prefixed models carry no
    entry in the engine's pricing table).
    """
    from app import store

    metrics = store.get_run_metrics(run_id, db_path=db_path) or {}
    model_usage = metrics.get("model_usage") or {}
    from evaluations._usage_evidence import summarize_usage

    evidence = summarize_usage(model_usage)
    return {
        "llm_calls": int(metrics.get("llm_calls", 0)),
        "tasks": tasks_count,
        "cost_usd": evidence["partial_estimated_total_usd"],
        "cost_basis": "partial_static_estimate",
        "usage_evidence": evidence,
        "latency_seconds": round(wall_clock_seconds, 3),
    }


def run_arm(
    goal: str,
    tier: str,
    overrides: dict[str, Any],
    invocation: ArmInvocation,
) -> dict[str, Any]:
    """Persist, drive, and collect one controlled-experiment arm.

    Returns:
        A plain dict carrying every field either driver needs to shape into
        its own artifact schema: ``run_id``, ``tier``, ``overrides``,
        ``completed``, ``used_offline``, ``events``, ``hypotheses`` (each
        annotated with claim counts), and ``metrics``.
    """
    from app import store

    db_path = invocation.db_path
    run_id = persist_arm_run(goal, tier, overrides, invocation)
    from co_scientist.cache import scoped_cache_override

    with scoped_cache_override(False):
        events, elapsed = drive_arm_run(run_id, db_path)
    run = store.get_run(run_id, db_path=db_path)
    completed, real_backend = run_completion_status(run)
    hyps = store.list_hypotheses(run_id, db_path=db_path)
    claim_edges = store.list_claim_evidence(run_id, db_path=db_path)
    tasks_count = len(store.list_tasks(run_id, db_path=db_path))
    return {
        "run_id": run_id,
        "evaluation_identity": run.config["evaluation_identity"],
        "tier": tier,
        "overrides": overrides,
        "completed": completed,
        "used_real_backend": real_backend,
        "events": events,
        "hypotheses": hypotheses_with_claim_counts(hyps, claim_edges),
        "metrics": compute_arm_metrics(run_id, db_path, elapsed, tasks_count),
    }
