"""Live acceptance is local-only and requires a real backend; campaign mode
cannot authorize INDRA.
"""

from __future__ import annotations

import datetime
import os
import pathlib
import sys
import tempfile
from typing import Any

from evaluations import _run_driver
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
_TIER = "express"
# Tier overrides may raise, never lower, the smallest durable baseline.
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


def _configure_env(db_path: str) -> None:
    model = os.getenv("MODEL_NAME", "").strip()
    if not model or "/" not in model:
        raise ValueError(
            "golden run requires explicit provider/model MODEL_NAME"
        )
    if "app.config" in sys.modules:
        raise RuntimeError("golden run requires a fresh process")
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    for role in (
        "MODEL_NAME",
        "SUPERVISOR_MODEL_NAME",
        "CHAT_MODEL_NAME",
        "SEMANTIC_SAFETY_MODEL",
        "CLAIM_VERIFIER_MODEL",
    ):
        os.environ[role] = model
    os.environ["MCP_SERVER_URL"] = "http://localhost:8888/mcp"
    os.environ["TOOLS_CONFIG"] = str(_INDRA_CONFIG)
    os.environ["CLAIM_ASSESSOR"] = "llm"
    os.environ["COSCIENTIST_DB_PATH"] = db_path
    os.environ.pop("FORCE_LITERATURE_REVIEW", None)
    os.environ.pop("COSCIENTIST_FORCE_OFFLINE", None)
    os.environ.pop("COSCIENTIST_FORCE_MOCK", None)


def _install_tool_call_counter() -> dict[str, int]:
    """Count both direct and model-requested tools independently of later
    evidence reshaping.
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
    """Pin real backend so missing credentials fail rather than satisfy
    acceptance with offline artifacts.
    """
    from app.run_modes import resolved_run_config, setup_config
    from app.store import runs
    from app.store.runs import RunCreateOptions

    config = resolved_run_config(
        {
            "setup": setup_config(research_goal=_GOAL, tier=_TIER),
            "tier": _TIER,
            "evidence_count": _EVIDENCE_COUNT,
            "enable_literature_review": True,
        }
    )
    run = runs.create_run(
        _GOAL,
        _TIER,
        "engine",
        config,
        RunCreateOptions(
            client_id="golden-run",
            llm_backend="real",
            db_path=db_path,
        ),
    )
    return str(run.id)


def _collect(run_id: str, db_path: str) -> dict[str, Any]:
    from app.store import hypotheses as store_hypotheses
    from app.store import records as store
    from app.store import reports
    from app.store import retrieval_calls as retrieval
    from app.store import runs as store_runs

    evidence = store.list_evidence(run_id, db_path=db_path)
    claim_edges = store.list_claim_evidence(run_id, db_path=db_path)
    matches = store.list_matches(run_id, db_path=db_path)
    report = reports.get_latest_report(run_id, db_path=db_path)
    hypotheses = store_hypotheses.list_hypotheses(run_id, db_path=db_path)
    return {
        "evidence": evidence,
        "claim_edges": claim_edges,
        "matches": matches,
        "report": report,
        "hypotheses": hypotheses,
        "run": store_runs.get_run(run_id, db_path=db_path),
        "metrics": retrieval.get_run_metrics(run_id, db_path=db_path),
    }


def _cost_summary(metrics: dict[str, Any] | None) -> dict[str, Any]:
    """Legacy cost estimates are not billing receipts; report completeness
    separately.
    """
    from evaluations._usage_evidence import summarize_usage

    usage = (metrics or {}).get("model_usage") or {}
    evidence = summarize_usage(usage)
    return {
        "total_usd": evidence["partial_estimated_total_usd"],
        "cost_basis": "partial_static_estimate",
        "usage_evidence": evidence,
        "llm_calls": (metrics or {}).get("llm_calls"),
        "by_phase_model": {
            key: round(float(v.get("cost_usd") or 0.0), 6)
            for key, v in usage.items()
        },
    }


def _support_passages(
    claim_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for edge in claim_edges:
        for key in ("supporting", "contradicting"):
            for span in edge.get(key) or []:
                if isinstance(span, dict):
                    spans.append(span)
    return spans


def _assess(
    collected: dict[str, Any], tool_calls: dict[str, int]
) -> dict[str, Any]:
    evidence = collected["evidence"]
    sources = sorted({str(e.get("source") or "") for e in evidence})
    indra_calls = {t: c for t, c in tool_calls.items() if t in _INDRA_TOOLS}
    spans = _support_passages(collected["claim_edges"])
    nonempty_spans = [s for s in spans if str(s.get("quote") or "").strip()]
    completed, real_backend = _run_driver.run_completion_status(
        collected["run"]
    )

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
    """Read resolved settings so provenance records the run's actual
    configuration.
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
            "Export MODEL_NAME and its provider key; "
            ".venv/bin/python -m evaluations.golden_run"
        ),
        "captured_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def run() -> dict[str, Any]:
    # LiteLLM may load dotenv during the engine import itself.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    from co_scientist.llm import campaign_free_mode

    if campaign_free_mode():
        raise RuntimeError(
            "INDRA golden acceptance is unavailable under campaign "
            "tool policy; "
            "use the campaign public-evidence workflow"
        )
    tmp_db = tempfile.mkdtemp(prefix="golden-run-")
    db_path = str(pathlib.Path(tmp_db) / "golden.db")
    _configure_env(db_path)

    from app.config import has_provider_credential, settings

    if not has_provider_credential(settings.model_name):
        raise SystemExit("no environment credential for explicit MODEL_NAME")

    tool_calls = _install_tool_call_counter()

    from app import engine_adapter

    # Validate config because silent fallback could pass without loading the
    # requested INDRA tools.
    engine_adapter.validate_tools_config(settings.tools_config)

    run_id = _persist_run(db_path)
    events, _elapsed = _run_driver.drain_run(
        run_id, db_path, worker_prefix="golden-run"
    )
    collected = _collect(run_id, db_path)
    assessment = _assess(collected, tool_calls)
    return _build_report(run_id, events, collected, assessment)


# Tournament pairing seeds by goal/cycle; provider completions have no single
# run-wide seed.
_SEED_DESCRIPTION = (
    "no global seed; tournament pairing is deterministic from "
    "hash(research_goal, iteration) -- see ranking.py; LLM sampling is "
    "provider-default (unseeded)"
)


def main() -> int:
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
