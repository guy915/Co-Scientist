"""Local MCP-backed golden run.

Drives one small biomedical run through the real production path -- the
durable task queue (``store.create_run`` -> ``task_worker`` ->
``engine_tasks`` -> engine -> MCP/INDRA -> drain -> report) against the LOCAL
MCP server, with the INDRA cancer tools config and the semantic (LLM) claim
assessor enabled, then asserts the acceptance from the persisted store and
writes a reproducibility artifact under ``evaluations/results/``.

The run is delivered exactly as ``POST /api/runs/{id}/start`` delivers one:
the run row is persisted, ``task_worker.enqueue_run_workflow`` puts
``engine.bootstrap`` on the queue, and a bounded worker cohort
(``run_run_worker_pool``, the same one the embedded API worker launches)
drains the resulting node/fan-out/tournament task chain to a terminal state.
There is no in-process streaming drive any more, so the acceptance is read
from the persisted event log and store rather than from a stream.

Acceptance (P0.6): the run completes on the real (not offline) backend with
nonzero *real* evidence records, nonempty support passages, and at least one
authorized INDRA tool invocation with ``indra_cancer.yaml`` -- the live
acceptance behind CITE-CLAIM-001 and TOOLS-CONFIG-001.

Run size comes from the tier, not from this script: the durable path
re-resolves the persisted config through ``resolved_run_config``, whose
numeric knobs may only raise a tier baseline. ``express`` is therefore the
smallest run available, and only ``evidence_count`` is raised above it (more
retrieved evidence is what the two cited requirements are about).

This makes real provider (DeepSeek) + MCP (PubMed/INDRA) calls and is run out of
band, never in CI. It is LOCAL only; it never touches Railway prod. Re-running
is safe (fresh temp DB each time).

Run:
    DEEPSEEK_API_KEY=... .venv/bin/python -m evaluations.golden_run
"""

from __future__ import annotations

import asyncio
import datetime
import os
import pathlib
import sys
import tempfile
from typing import Any

from evaluations._artifacts import write_dated_artifact

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_INDRA_CONFIG = (
    _ROOT
    / "engine"
    / "src"
    / "co_scientist"
    / "config"
    / "examples"
    / "indra_cancer.yaml"
)
# The viewer backend is imported as a plain package from the repo root, the
# same way the offline evals reach it (see citation_eval). The engine is a
# real installed dependency and needs no path help.
sys.path.insert(0, str(_ROOT / "app"))

# Smallest tier the durable path can execute; see the module docstring.
_TIER = "express"
# Raised above the express baseline (4): evidence is what the two cited
# requirements are asserted over. Overrides may only raise, never lower.
_EVIDENCE_COUNT = 6

_INDRA_TOOLS = {
    "query_mechanistic_statements",
    "query_gene_disease_network",
    "query_drug_info",
    "query_gene_codependents",
    "query_pathways",
    "query_clinical_trials",
    "query_causal_subnetwork",
    "run_enrichment_analysis",
}

_GOAL = (
    "Identify a novel small-molecule combination to overcome osimertinib "
    "resistance in EGFR-mutant non-small-cell lung cancer."
)


def _load_provider_key() -> str:
    """Read DEEPSEEK_API_KEY from the environment or the checkout's .env."""
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    env_file = _ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def _configure_env(db_path: str) -> None:
    """Set the run's environment BEFORE any app import loads settings.

    Literature review is left enabled (no FORCE_LITERATURE_REVIEW=0), so the
    INDRA/PubMed search tools actually run — the whole point of the golden run.
    ``MODEL_NAME`` is deliberately not pinned here: an operator override is
    honoured, and otherwise the app's own default model applies, so the
    artifact records what actually ran instead of a name frozen in this file.
    Forcing the offline backend would make every acceptance check vacuous, so
    it is cleared rather than trusted.
    """
    os.environ["MCP_SERVER_URL"] = "http://localhost:8888/mcp"
    os.environ["TOOLS_CONFIG"] = str(_INDRA_CONFIG)
    os.environ["CLAIM_ASSESSOR"] = "llm"
    os.environ["COSCIENTIST_DB_PATH"] = db_path
    os.environ["DEEPSEEK_API_KEY"] = _load_provider_key()
    os.environ.pop("FORCE_LITERATURE_REVIEW", None)
    os.environ.pop("COSCIENTIST_FORCE_OFFLINE", None)
    os.environ.pop("COSCIENTIST_FORCE_MOCK", None)


def _install_tool_call_counter() -> dict[str, int]:
    """Patch the MCP client so every tool invocation is counted by name.

    Lit-review search calls ``call_tool``; tool-calling generation (if any)
    calls ``execute_tool_call``. Both are wrapped so the counts are ground
    truth for "which MCP tools were actually invoked", independent of how
    evidence is later shaped.
    """
    from co_scientist import mcp_client

    counts: dict[str, int] = {}
    orig_call = mcp_client.MCPToolClient.call_tool
    orig_exec = mcp_client.MCPToolClient.execute_tool_call

    async def _counted_call(self: Any, tool_name: str, **kwargs: Any) -> Any:
        counts[tool_name] = counts.get(tool_name, 0) + 1
        return await orig_call(self, tool_name, **kwargs)

    async def _counted_exec(self: Any, tool_call: Any) -> Any:
        name = getattr(getattr(tool_call, "function", None), "name", "?")
        counts[name] = counts.get(name, 0) + 1
        return await orig_exec(self, tool_call)

    client = mcp_client.MCPToolClient
    client.call_tool = _counted_call  # type: ignore[method-assign]
    client.execute_tool_call = _counted_exec  # type: ignore[method-assign]
    return counts


def _persist_run(db_path: str) -> str:
    """Create the run row the durable queue will execute, returning its id.

    Mirrors what ``POST /api/runs`` persists: a config resolved through
    ``resolved_run_config`` around a real planning ``setup`` block, so the
    engine receives the same guidance a UI-created run would. The backend is
    pinned to "real" rather than left for ``offline_mode()`` to decide, so a
    missing key fails the run instead of quietly producing an offline
    artifact that would satisfy every check below.
    """
    from app import store
    from app.run_modes import resolved_run_config, setup_config

    config = resolved_run_config(
        {
            "setup": setup_config(research_goal=_GOAL, tier=_TIER),
            "tier": _TIER,
            "evidence_count": _EVIDENCE_COUNT,
            "enable_literature_review": True,
        }
    )
    run = store.create_run(
        _GOAL,
        _TIER,
        "engine",
        config,
        store.RunCreateOptions(
            client_id="golden-run",
            llm_backend="real",
            db_path=db_path,
        ),
    )
    return str(run.id)


def _drive_run(run_id: str, db_path: str) -> int:
    """Drain the run's durable task chain, returning its persisted event count.

    The same two steps ``POST /{id}/start`` performs: enqueue the run's
    ``engine.bootstrap`` task, then run a bounded worker cohort over the
    queue. The cohort returns once no ready task and no live lease remain --
    i.e. once the run has reached a terminal state -- so no polling is
    needed. It runs on its own event loop, as every cohort does.
    """
    from app import store, task_worker

    task_worker.enqueue_run_workflow(
        run_id, force_provider="engine", db_path=db_path
    )
    asyncio.run(
        task_worker.run_run_worker_pool(
            run_id,
            f"golden-run:{run_id[:8]}",
            policy=task_worker.WorkerPolicy(db_path=db_path),
        )
    )
    return len(store.list_events(run_id, db_path=db_path))


def _collect(run_id: str, db_path: str) -> dict[str, Any]:
    """Read the persisted artifacts the acceptance is asserted against."""
    from app import store

    evidence = store.list_evidence(run_id, db_path=db_path)
    claim_edges = store.list_claim_evidence(run_id, db_path=db_path)
    matches = store.list_matches(run_id, db_path=db_path)
    report = store.get_latest_report(run_id, db_path=db_path)
    hypotheses = store.list_hypotheses(run_id, db_path=db_path)
    return {
        "evidence": evidence,
        "claim_edges": claim_edges,
        "matches": matches,
        "report": report,
        "hypotheses": hypotheses,
        "run": store.get_run(run_id, db_path=db_path),
        "metrics": store.get_run_metrics(run_id, db_path=db_path),
    }


def _cost_summary(metrics: dict[str, Any] | None) -> dict[str, Any]:
    """Roll the run's persisted ``model_usage`` telemetry into a cost total.

    ``model_usage`` is keyed ``"{phase}::{model}"`` (see
    ``co_scientist.models_metrics.ExecutionMetrics``); this sums the
    ``cost_usd`` every key carries so the golden-run artifact records what
    the run actually cost rather than leaving cost as an external unknown.
    """
    usage = (metrics or {}).get("model_usage") or {}
    total = sum(float(v.get("cost_usd") or 0.0) for v in usage.values())
    return {
        "total_usd": round(total, 6),
        "llm_calls": (metrics or {}).get("llm_calls"),
        "by_phase_model": {
            key: round(float(v.get("cost_usd") or 0.0), 6)
            for key, v in usage.items()
        },
    }


def _support_passages(
    claim_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten every supporting/contradicting span across all claim edges."""
    spans: list[dict[str, Any]] = []
    for edge in claim_edges:
        for key in ("supporting", "contradicting"):
            for span in edge.get(key) or []:
                if isinstance(span, dict):
                    spans.append(span)
    return spans


def _run_reached_real_completion(
    collected: dict[str, Any],
) -> tuple[bool, bool]:
    """Return (completed, ran_on_the_real_backend) for the persisted run row.

    The durable cohort returns when the queue drains, which a *failed* run
    also does; and a keyless environment would answer every LLM call from the
    deterministic offline backend. Neither was expressible on the streaming
    path, and both would otherwise pass the evidence checks below.
    """
    from app import store

    run = collected["run"]
    if run is None:
        return False, False
    completed = run.status == store.RunStatus.COMPLETED.value
    return completed, not store.run_used_offline(run)


def _assess(
    collected: dict[str, Any], tool_calls: dict[str, int]
) -> dict[str, Any]:
    """Compute the acceptance checks over the persisted artifacts."""
    evidence = collected["evidence"]
    sources = sorted({str(e.get("source") or "") for e in evidence})
    indra_calls = {t: c for t, c in tool_calls.items() if t in _INDRA_TOOLS}
    spans = _support_passages(collected["claim_edges"])
    nonempty_spans = [s for s in spans if str(s.get("quote") or "").strip()]
    completed, real_backend = _run_reached_real_completion(collected)

    checks = {
        "run_completed": completed,
        "real_llm_backend": real_backend,
        "nonzero_evidence": len(evidence) > 0,
        "no_mock_sources": bool(evidence) and "mock" not in sources,
        "at_least_one_indra_invocation": sum(indra_calls.values()) > 0,
        "nonempty_support_passages": len(nonempty_spans) > 0,
        "report_produced": collected["report"] is not None,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "evidence_count": len(evidence),
        "evidence_sources": sources,
        "tool_calls": dict(sorted(tool_calls.items())),
        "indra_calls": dict(sorted(indra_calls.items())),
        "claim_edge_count": len(collected["claim_edges"]),
        "support_span_count": len(nonempty_spans),
        "match_count": len(collected["matches"]),
        "hypothesis_count": len(collected["hypotheses"]),
    }


def _sample_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A compact evidence sample for the artifact (title/source/url only)."""
    return [
        {
            "title": e.get("title"),
            "source": e.get("source"),
            "url": e.get("url"),
            "has_abstract": bool(e.get("abstract")),
        }
        for e in evidence[:6]
    ]


def _sample_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A compact support-span sample for the artifact."""
    return [
        {
            "evidence_id": s.get("evidence_id"),
            "quote": s.get("quote"),
            "url": s.get("url"),
        }
        for s in spans[:6]
    ]


def _build_report(
    run_id: str,
    events: int,
    collected: dict[str, Any],
    assessment: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the reproducibility report payload.

    Configuration is read back from the resolved settings rather than from
    the environment this script wrote, so the artifact records what the run
    actually used (notably the model, which is no longer pinned here).
    """
    from app.config import settings

    report_row = collected["report"] or {}
    return {
        "goal": _GOAL,
        "provider": "engine",
        "run_path": "durable",
        "tier": _TIER,
        "model": settings.model_name,
        "mcp_server_url": settings.mcp_server_url,
        "tools_config": settings.tools_config,
        "claim_assessor": settings.claim_assessor,
        "run_id": run_id,
        "events_recorded": events,
        "acceptance": assessment,
        "evidence_sample": _sample_evidence(collected["evidence"]),
        "support_span_sample": _sample_spans(
            _support_passages(collected["claim_edges"])
        ),
        "report_hypothesis_count": (report_row.get("payload") or {}).get(
            "hypothesis_count"
        ),
        "cost": _cost_summary(collected["metrics"]),
        "reproduce": (
            "DEEPSEEK_API_KEY=... .venv/bin/python -m evaluations.golden_run"
        ),
        "captured_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def run() -> dict[str, Any]:
    """Execute the golden run and return the reproducibility report."""
    tmp_db = tempfile.mkdtemp(prefix="golden-run-")
    db_path = str(pathlib.Path(tmp_db) / "golden.db")
    _configure_env(db_path)

    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("no DEEPSEEK_API_KEY available; cannot run")

    tool_calls = _install_tool_call_counter()

    from app import engine_adapter
    from app.config import settings

    # The app lifespan validates this before serving; without it a bad
    # TOOLS_CONFIG silently falls back to default tools and the run would
    # "pass" having never loaded indra_cancer.yaml at all.
    engine_adapter.validate_tools_config(settings.tools_config)

    run_id = _persist_run(db_path)
    events = _drive_run(run_id, db_path)
    collected = _collect(run_id, db_path)
    assessment = _assess(collected, tool_calls)
    return _build_report(run_id, events, collected, assessment)


# The engine seeds nothing globally: tournament pairing derives a
# deterministic per-call seed from `md5(research_goal + iteration)` (see
# `agents/ranking/ranking.py::_build_tournament_pairings`), and every LLM
# completion is otherwise provider-default (unseeded). Recorded as a
# description, not a number, since there is no single seed value for the
# run.
_SEED_DESCRIPTION = (
    "no global seed; tournament pairing is deterministic from "
    "hash(research_goal, iteration) -- see ranking.py; LLM sampling is "
    "provider-default (unseeded)"
)


def main() -> int:
    """Run the golden run, write the artifact, print a compact summary."""
    report = run()
    out = write_dated_artifact(
        report,
        "golden-run-indra",
        model=report["model"],
        seed=_SEED_DESCRIPTION,
        cost=report["cost"],
    )

    a = report["acceptance"]
    print(f"golden run: {'PASS' if a['passed'] else 'FAIL'}")
    print(
        f"  evidence={a['evidence_count']} sources={a['evidence_sources']} "
        f"claim_edges={a['claim_edge_count']} spans={a['support_span_count']}"
    )
    print(f"  indra_calls={a['indra_calls']}")
    print(f"  checks={a['checks']}")
    print(f"wrote {out}")
    return 0 if a["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
